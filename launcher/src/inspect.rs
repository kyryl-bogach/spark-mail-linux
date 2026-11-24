//! Hand a URL to the running Spark through its Node inspector.
//!
//! On x86_64 hosts a second `Spark Desktop.exe` passes its arguments to the
//! first instance and exits. Under FEX that second process makes the first
//! one die, so the launcher never starts one. Spark is started with
//! `--inspect` bound to the VM's loopback instead, and this module asks the
//! main process to raise the same `second-instance` event itself.
//!
//! The client speaks just enough HTTP and WebSocket for one request.

use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::time::Duration;

/// Executable name Spark sees in the forwarded argument list.
const EXE_NAME: &str = "Spark Desktop.exe";
/// Value the expression returns when Spark took the event.
const DELIVERED: &str = "delivered";
const TIMEOUT: Duration = Duration::from_secs(20);

/// Encode text as a JSON (and JavaScript) string literal.
pub fn json_string(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 2);
    out.push('"');
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            // Escaped so the text can sit inside any script context.
            c if c.is_control() || matches!(c, '<' | '>' | '\u{2028}' | '\u{2029}') => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// JavaScript that raises Spark's `second-instance` event in the main process.
///
/// Spark does not read the event's argument list directly. A second instance
/// adds `--second-instance=<its argv as JSON>`, and the first instance parses
/// that switch. With no URL the event only shows the window.
pub fn delivery_expression(url: Option<&str>) -> String {
    let mut forwarded = vec![json_string(EXE_NAME)];
    if let Some(url) = url {
        forwarded.push(json_string("--win-open-url"));
        forwarded.push(json_string(url));
    }
    format!(
        "require('electron').app.emit('second-instance', {{}}, [process.execPath, \
         '--second-instance=' + JSON.stringify([{}])], process.cwd()) ? '{DELIVERED}' : 'no-listener'",
        forwarded.join(",")
    )
}

/// The inspector request that evaluates one expression.
pub fn evaluate_request(expression: &str) -> String {
    format!(
        "{{\"id\":1,\"method\":\"Runtime.evaluate\",\"params\":{{\"expression\":{},\
         \"returnByValue\":true,\"includeCommandLineAPI\":true}}}}",
        json_string(expression)
    )
}

/// Path of the first debugging target in a `/json/list` reply.
pub fn debugger_path(json_list: &str) -> Option<String> {
    let key = "\"webSocketDebuggerUrl\"";
    let after_key = &json_list[json_list.find(key)? + key.len()..];
    let value = after_key.trim_start().strip_prefix(':')?.trim_start();
    let url = value.strip_prefix('"')?.split('"').next()?;
    let rest = url.strip_prefix("ws://")?;
    let path = &rest[rest.find('/')?..];
    let safe = path
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '/' | '-' | '_' | '.'));
    safe.then(|| path.to_owned())
}

/// One masked text frame, as a WebSocket client must send it.
pub fn text_frame(payload: &[u8], mask: [u8; 4]) -> Vec<u8> {
    let mut frame = vec![0x81];
    match payload.len() {
        len @ 0..=125 => frame.push(0x80 | len as u8),
        len @ 126..=0xffff => {
            frame.push(0x80 | 126);
            frame.extend_from_slice(&(len as u16).to_be_bytes());
        }
        len => {
            frame.push(0x80 | 127);
            frame.extend_from_slice(&(len as u64).to_be_bytes());
        }
    }
    frame.extend_from_slice(&mask);
    frame.extend(payload.iter().zip(mask.iter().cycle()).map(|(b, m)| b ^ m));
    frame
}

/// Read one unmasked frame from the server and return its payload.
pub fn read_frame(stream: &mut impl Read) -> io::Result<Vec<u8>> {
    let mut head = [0u8; 2];
    stream.read_exact(&mut head)?;
    let len = match head[1] & 0x7f {
        126 => {
            let mut ext = [0u8; 2];
            stream.read_exact(&mut ext)?;
            u64::from(u16::from_be_bytes(ext))
        }
        127 => {
            let mut ext = [0u8; 8];
            stream.read_exact(&mut ext)?;
            u64::from_be_bytes(ext)
        }
        short => u64::from(short),
    };
    if head[1] & 0x80 != 0 || len > 1 << 20 {
        return Err(io::Error::other("unexpected WebSocket frame"));
    }
    let mut payload = vec![0u8; len as usize];
    stream.read_exact(&mut payload)?;
    Ok(payload)
}

/// True when the inspector's reply says Spark took the event.
pub fn reply_delivered(reply: &str) -> bool {
    reply.contains(&format!("\"value\":\"{DELIVERED}\""))
}

fn connect(port: u16) -> io::Result<TcpStream> {
    let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let stream = TcpStream::connect_timeout(&address, TIMEOUT)?;
    stream.set_read_timeout(Some(TIMEOUT))?;
    stream.set_write_timeout(Some(TIMEOUT))?;
    Ok(stream)
}

fn read_headers(stream: &mut impl Read) -> io::Result<String> {
    let mut head = Vec::new();
    let mut byte = [0u8; 1];
    while !head.ends_with(b"\r\n\r\n") {
        if head.len() > 16 * 1024 {
            return Err(io::Error::other("oversized HTTP header"));
        }
        stream.read_exact(&mut byte)?;
        head.push(byte[0]);
    }
    Ok(String::from_utf8_lossy(&head).into_owned())
}

/// `Content-Length` of an HTTP header block.
pub fn content_length(head: &str) -> Option<usize> {
    head.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("content-length")
            .then(|| value.trim().parse().ok())?
    })
}

fn target_path(port: u16) -> io::Result<String> {
    let mut stream = connect(port)?;
    write!(
        stream,
        "GET /json/list HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    )?;
    // The inspector keeps the connection open, so read exactly the body.
    let head = read_headers(&mut stream)?;
    let length = content_length(&head)
        .filter(|length| *length <= 1 << 20)
        .ok_or_else(|| io::Error::other("no usable Content-Length from the inspector"))?;
    let mut body = vec![0u8; length];
    stream.read_exact(&mut body)?;
    debugger_path(&String::from_utf8_lossy(&body))
        .ok_or_else(|| io::Error::other("no debugging target in the reply"))
}

/// Deliver a URL (or a plain "show the window") to Spark on the local
/// inspector port. Must run inside the VM, where that port listens.
pub fn deliver(port: u16, url: Option<&str>) -> io::Result<()> {
    let path = target_path(port)?;
    let mut stream = connect(port)?;
    // The key only has to be 16 base64-encoded bytes; this is RFC 6455's sample.
    write!(
        stream,
        "GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n\
         Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\
         Sec-WebSocket-Version: 13\r\n\r\n"
    )?;
    let head = read_headers(&mut stream)?;
    if !head.starts_with("HTTP/1.1 101") {
        return Err(io::Error::other("the inspector refused the connection"));
    }
    let request = evaluate_request(&delivery_expression(url));
    // Masking guards browsers against proxies; on loopback the value is irrelevant.
    stream.write_all(&text_frame(
        request.as_bytes(),
        std::process::id().to_be_bytes(),
    ))?;
    let reply = read_frame(&mut stream)?;
    if reply_delivered(&String::from_utf8_lossy(&reply)) {
        Ok(())
    } else {
        Err(io::Error::other("Spark did not take the event"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;

    #[test]
    fn json_strings_escape_quotes_and_controls() {
        assert_eq!(json_string("a\"b\\c"), r#""a\"b\\c""#);
        // Angle brackets are written as escapes, built here from parts.
        let (lt, gt) = (format!("{}u003c", '\\'), format!("{}u003e", '\\'));
        assert_eq!(
            json_string("a\nb</script>"),
            format!("\"a\\u000ab{lt}/script{gt}\"")
        );
        assert_eq!(json_string("é✓"), "\"é✓\"");
    }

    #[test]
    fn expression_wraps_the_url_the_way_spark_expects() {
        let expr = delivery_expression(Some("readdle-spark://x?a='1'&b=\"2\""));
        assert!(expr.contains(
            r#"JSON.stringify(["Spark Desktop.exe","--win-open-url","readdle-spark://x?a='1'&b=\"2\""])"#
        ));
        assert!(expr.contains("'--second-instance=' +"));
        assert!(delivery_expression(None).contains(r#"JSON.stringify(["Spark Desktop.exe"])"#));
    }

    #[test]
    fn finds_the_debugger_path() {
        let reply = "HTTP/1.1 200 OK\r\n\r\n[ {\n  \"type\": \"node\",\n  \"webSocketDebuggerUrl\": \"ws://127.0.0.1:9229/0f2c-ab_1\"\n} ]";
        assert_eq!(debugger_path(reply).as_deref(), Some("/0f2c-ab_1"));
        assert_eq!(debugger_path("[]"), None);
        let hostile = "\"webSocketDebuggerUrl\": \"ws://h/a\r\nX: y\"";
        assert_eq!(debugger_path(hostile), None);
    }

    #[test]
    fn reads_content_length_in_any_case() {
        let head =
            "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\ncontent-length: 42\r\n\r\n";
        assert_eq!(content_length(head), Some(42));
        assert_eq!(content_length("HTTP/1.0 200 OK\r\n\r\n"), None);
    }

    #[test]
    fn frames_round_trip() {
        let mask = [1, 2, 3, 4];
        assert_eq!(
            text_frame(b"hi", mask),
            [0x81, 0x82, 1, 2, 3, 4, b'h' ^ 1, b'i' ^ 2]
        );
        let long = vec![b'x'; 300];
        let frame = text_frame(&long, mask);
        assert_eq!(&frame[..4], [0x81, 0x80 | 126, 1, 44]);
        assert_eq!(frame.len(), 4 + 4 + 300);
        let mut server_frame = vec![0x81, 126, 1, 44];
        server_frame.extend_from_slice(&long);
        assert_eq!(read_frame(&mut server_frame.as_slice()).unwrap(), long);
        assert!(read_frame(&mut [0x81u8, 0x82, 0, 0].as_slice()).is_err());
    }

    /// A stand-in inspector: serves the target list, then one WebSocket
    /// session, and returns the request it received.
    fn fake_inspector(listener: TcpListener, value: &'static str) -> thread::JoinHandle<String> {
        thread::spawn(move || {
            let port = listener.local_addr().unwrap().port();
            let (mut http, _) = listener.accept().unwrap();
            read_headers(&mut http).unwrap();
            let body = format!("[{{\"webSocketDebuggerUrl\": \"ws://127.0.0.1:{port}/abc-1\"}}]");
            write!(
                http,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n{body}",
                body.len()
            )
            .unwrap();
            // Like the real inspector, leave this connection open.
            let (mut ws, _) = listener.accept().unwrap();
            let head = read_headers(&mut ws).unwrap();
            assert!(head.starts_with("GET /abc-1 HTTP/1.1"));
            ws.write_all(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
                .unwrap();
            let mut head = [0u8; 4];
            ws.read_exact(&mut head).unwrap();
            assert_eq!(head[1], 0x80 | 126);
            let len = usize::from(u16::from_be_bytes([head[2], head[3]]));
            let mut mask = [0u8; 4];
            ws.read_exact(&mut mask).unwrap();
            let mut payload = vec![0u8; len];
            ws.read_exact(&mut payload).unwrap();
            for (byte, m) in payload.iter_mut().zip(mask.iter().cycle()) {
                *byte ^= m;
            }
            let reply = format!(
                "{{\"id\":1,\"result\":{{\"result\":{{\"type\":\"string\",\"value\":\"{value}\"}}}}}}"
            );
            let mut frame = vec![0x81, reply.len() as u8];
            frame.extend_from_slice(reply.as_bytes());
            ws.write_all(&frame).unwrap();
            String::from_utf8(payload).unwrap()
        })
    }

    #[test]
    fn delivers_over_a_real_socket() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = fake_inspector(listener, "delivered");
        deliver(port, Some("mailto:a@example.com")).unwrap();
        let request = server.join().unwrap();
        assert!(request.contains("Runtime.evaluate"));
        assert!(request.contains("mailto:a@example.com"));
    }

    #[test]
    fn reports_when_spark_has_no_listener() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = fake_inspector(listener, "no-listener");
        assert!(deliver(port, None).is_err());
        server.join().unwrap();
    }
}
