//! Links in both directions.
//!
//! Out: Wine inside the VM runs `xdg-open`. The VM has no desktop session, so
//! the guest side writes the target into a spool directory on the shared
//! filesystem and the launcher on the host opens it.
//!
//! In: the desktop hands callback and deep-link URLs to the launcher, which
//! checks the scheme before it forwards them into Spark.

use std::fs;
use std::io::{self, Write};
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

/// Schemes Spark handles. Keep in step with `bin/auth-callback.py` and
/// `share/spark-mail-linux-auth.desktop.in`; a test compares the latter.
pub const ALLOWED_SCHEMES: [&str; 12] = [
    "com.googleusercontent.apps.681834923750-3p9205dgnfbq0s196910u38tmn61ehc2",
    "com.readdle.spark.auth-bridge.desktop-dist",
    "com.readdle.spark.utm.email.desktop",
    "hotmail.com.readdle.smartmail.desktop",
    "mailto",
    "msauth.com.readdle.smartmail.desktop",
    "oauth.redirect.com.readdle.smartmail",
    "readdle-spark",
    "readdlespark",
    "spark-mail-url",
    "stripe.com.readdle.spark",
    "yahoo.com.readdle.smartmail.desktop",
];

const MAX_TARGET_LEN: usize = 16 * 1024;

fn has_control_chars(text: &str) -> bool {
    text.chars().any(char::is_control)
}

/// Lower-cased scheme of a URL, if it has one.
pub fn scheme_of(url: &str) -> Option<String> {
    let (scheme, _) = url.split_once(':')?;
    let mut chars = scheme.chars();
    let valid = chars.next().is_some_and(|c| c.is_ascii_alphabetic())
        && chars.all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '-' | '.'));
    valid.then(|| scheme.to_ascii_lowercase())
}

/// Scheme of a URL Spark may receive, or `None` when it must be refused.
pub fn spark_scheme(url: &str) -> Option<String> {
    if has_control_chars(url) || url.len() > MAX_TARGET_LEN {
        return None;
    }
    scheme_of(url).filter(|scheme| ALLOWED_SCHEMES.contains(&scheme.as_str()))
}

/// What the host may open on behalf of Spark.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HostTarget {
    Web(String),
    File(PathBuf),
}

impl HostTarget {
    /// Safe to log: never includes the URL or the file name.
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Web(_) => "web link",
            Self::File(_) => "file",
        }
    }
}

/// Decode `%XX` escapes. `None` for a broken escape or a result that is not UTF-8.
pub fn percent_decode(text: &str) -> Option<String> {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' {
            let hex = std::str::from_utf8(bytes.get(i + 1..i + 3)?).ok()?;
            out.push(u8::from_str_radix(hex, 16).ok()?);
            i += 3;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8(out).ok()
}

/// Accept web links and absolute file paths, refuse everything else.
pub fn classify_target(target: &str) -> Option<HostTarget> {
    if target.is_empty() || has_control_chars(target) || target.len() > MAX_TARGET_LEN {
        return None;
    }
    match scheme_of(target).as_deref() {
        Some("http" | "https") => {
            let rest = target.split_once("://")?.1;
            let host = rest.split(['/', '?', '#']).next().unwrap_or_default();
            (!host.is_empty()).then(|| HostTarget::Web(target.to_owned()))
        }
        Some("file") => {
            let path = percent_decode(target.get("file://".len()..)?)?;
            (path.starts_with('/') && !has_control_chars(&path))
                .then(|| HostTarget::File(PathBuf::from(path)))
        }
        Some(_) => None,
        None => target
            .starts_with('/')
            .then(|| HostTarget::File(PathBuf::from(target))),
    }
}

fn ensure_private_dir(dir: &Path) -> io::Result<()> {
    if !dir.is_dir() {
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(dir)?;
    }
    fs::set_permissions(dir, fs::Permissions::from_mode(0o700))
}

/// Write a file only its owner can read, inside a private directory.
pub fn write_private(path: &Path, content: &str) -> io::Result<()> {
    if let Some(dir) = path.parent() {
        ensure_private_dir(dir)?;
    }
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(content.as_bytes())?;
    file.sync_all()
}

/// Guest side: queue one target. The file appears under its final name only
/// when complete, so the host never reads half a URL.
pub fn enqueue(spool: &Path, target: &str) -> io::Result<()> {
    ensure_private_dir(spool)?;
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    let name = format!("{nanos:032}-{}", std::process::id());
    let partial = spool.join(format!("{name}.part"));
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&partial)?;
    file.write_all(target.as_bytes())?;
    file.sync_all()?;
    fs::rename(&partial, spool.join(format!("{name}.req")))
}

/// Host side: take every queued target, oldest first, and delete the files.
/// Sign-in URLs stay on disk only until the next poll.
pub fn drain(spool: &Path) -> io::Result<Vec<String>> {
    ensure_private_dir(spool)?;
    let mut requests: Vec<PathBuf> = fs::read_dir(spool)?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "req"))
        .collect();
    requests.sort();
    let mut targets = Vec::new();
    for path in requests {
        let content = fs::read_to_string(&path);
        fs::remove_file(&path)?;
        if let Ok(content) = content {
            targets.push(content);
        }
    }
    Ok(targets)
}

/// Remove everything left from an earlier session.
pub fn clear(spool: &Path) -> io::Result<()> {
    ensure_private_dir(spool)?;
    for entry in fs::read_dir(spool)?.filter_map(Result::ok) {
        fs::remove_file(entry.path())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_spark_schemes_in_any_case() {
        assert_eq!(
            spark_scheme("Readdle-Spark://open?x=1").as_deref(),
            Some("readdle-spark")
        );
        assert_eq!(
            spark_scheme("mailto:a@example.com").as_deref(),
            Some("mailto")
        );
    }

    #[test]
    fn refuses_other_schemes_and_control_characters() {
        assert_eq!(spark_scheme("https://example.com"), None);
        assert_eq!(spark_scheme("file:///etc/passwd"), None);
        assert_eq!(spark_scheme("--inspect=0.0.0.0"), None);
        assert_eq!(spark_scheme("readdle-spark://a\nb"), None);
        assert_eq!(spark_scheme("no scheme"), None);
    }

    #[test]
    fn classifies_host_targets() {
        assert_eq!(
            classify_target("HTTPS://accounts.example.com/o?a=b"),
            Some(HostTarget::Web("HTTPS://accounts.example.com/o?a=b".into()))
        );
        assert_eq!(
            classify_target("/home/u/a b.pdf"),
            Some(HostTarget::File("/home/u/a b.pdf".into()))
        );
        assert_eq!(
            classify_target("file:///home/u/a.pdf"),
            Some(HostTarget::File("/home/u/a.pdf".into()))
        );
        assert_eq!(
            classify_target("file:///home/u/Site%20report%20caf%C3%A9.pdf"),
            Some(HostTarget::File("/home/u/Site report café.pdf".into()))
        );
        for bad in [
            "file:///home/u/a%0Ab",
            "file:///home/u/a%zz",
            "file:///home/u/a%2",
            "",
            "https://",
            "https:///path",
            "javascript:alert(1)",
            "relative/path",
            "file://host/share",
            "https://a\u{7}b",
            "-flag",
        ] {
            assert_eq!(classify_target(bad), None, "{bad}");
        }
    }

    #[test]
    fn private_files_are_owner_only_and_never_overwritten() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("deliveries/1.url");
        write_private(&path, "mailto:a@example.com").unwrap();
        let mode = fs::metadata(&path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        assert!(write_private(&path, "x").is_err());
    }

    #[test]
    fn spool_round_trip_keeps_order_and_empties_the_directory() {
        let dir = tempfile::tempdir().unwrap();
        let spool = dir.path().join("open-requests");
        enqueue(&spool, "https://one.example").unwrap();
        enqueue(&spool, "https://two.example").unwrap();
        fs::write(spool.join("half-written.part"), "https://no").unwrap();
        assert_eq!(
            drain(&spool).unwrap(),
            ["https://one.example", "https://two.example"]
        );
        assert!(drain(&spool).unwrap().is_empty());
        let mode = fs::metadata(&spool).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o700);
        clear(&spool).unwrap();
        assert_eq!(fs::read_dir(&spool).unwrap().count(), 0);
    }
}
