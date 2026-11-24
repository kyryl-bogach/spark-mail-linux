//! Desktop entries: the launcher icon and the handler for Spark's URL schemes.

use std::path::Path;

use crate::links::ALLOWED_SCHEMES;

pub const LAUNCHER_FILE: &str = "spark-mail-linux.desktop";
pub const HANDLER_FILE: &str = "spark-mail-linux-auth.desktop";
const BACKSLASH: char = 92 as char;

/// Quote one argument for a desktop entry `Exec` line. Returns `None` for
/// characters that need the spec's two layers of escaping, which is easy to
/// get wrong; such paths are refused instead.
pub fn exec_quote(arg: &str) -> Option<String> {
    let refused = |c: char| c.is_control() || matches!(c, '%' | '"' | '`' | '$' | BACKSLASH);
    if arg.is_empty() || arg.chars().any(refused) {
        return None;
    }
    Some(format!("\"{arg}\""))
}

fn exec_prefix(exe: &Path, root: &Path) -> Option<String> {
    Some(format!(
        "{} --root {}",
        exec_quote(exe.to_str()?)?,
        exec_quote(root.to_str()?)?
    ))
}

/// MIME types the handler entry claims, one per allowed scheme.
pub fn handler_mime_types() -> Vec<String> {
    ALLOWED_SCHEMES
        .iter()
        .map(|scheme| format!("x-scheme-handler/{scheme}"))
        .collect()
}

pub fn launcher_entry(exe: &Path, root: &Path) -> Option<String> {
    Some(format!(
        "[Desktop Entry]\nType=Application\nName=Spark Mail\nComment=Smart email client\nExec={}\nIcon=mail-unread\nTerminal=false\nStartupNotify=true\nStartupWMClass=spark desktop.exe\nCategories=Network;Email;\nKeywords=email;mail;spark;\n",
        exec_prefix(exe, root)?
    ))
}

/// `--` stops a crafted link from being read as a launcher option.
pub fn handler_entry(exe: &Path, root: &Path) -> Option<String> {
    Some(format!(
        "[Desktop Entry]\nType=Application\nName=Spark Mail Linux Link Handler\nExec={} -- %u\nNoDisplay=true\nTerminal=false\nMimeType={};\n",
        exec_prefix(exe, root)?,
        handler_mime_types().join(";")
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quotes_exec_arguments() {
        assert_eq!(exec_quote("/a b/c").as_deref(), Some("\"/a b/c\""));
        assert_eq!(exec_quote("/a$b"), None);
        assert_eq!(exec_quote(&format!("/a{BACKSLASH}b")), None);
        assert_eq!(exec_quote("/a%u"), None);
        assert_eq!(exec_quote("/a\nb"), None);
    }

    #[test]
    fn entries_point_at_the_launcher() {
        let exe = Path::new("/r/.build/spark-arm");
        let root = Path::new("/r");
        let launcher = launcher_entry(exe, root).unwrap();
        assert!(launcher.contains("\nExec=\"/r/.build/spark-arm\" --root \"/r\"\n"));
        let handler = handler_entry(exe, root).unwrap();
        assert!(handler.contains("\nExec=\"/r/.build/spark-arm\" --root \"/r\" -- %u\n"));
        assert!(handler.contains("x-scheme-handler/readdle-spark;"));
    }

    /// The scheme list has one source upstream: the handler template.
    #[test]
    fn schemes_match_the_upstream_template() {
        let template = include_str!("../../share/spark-mail-linux-auth.desktop.in");
        let line = template
            .lines()
            .find_map(|line| line.strip_prefix("MimeType="))
            .unwrap();
        let mut upstream: Vec<&str> = line.split(';').filter(|m| !m.is_empty()).collect();
        upstream.sort_unstable();
        let mut ours = handler_mime_types();
        ours.sort_unstable();
        assert_eq!(ours, upstream);
    }
}
