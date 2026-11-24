//! Pure logic for the microVM: command building, instance detection, retries.

use std::path::{Path, PathBuf};
use std::time::Duration;

/// Windows executable name inside the app directory.
pub const SPARK_EXE: &str = "Spark Desktop.exe";

/// Same overrides as `run-spark.sh`.
pub const DLL_OVERRIDES: &str = "winemenubuilder.exe=d;powershell.exe,pwsh.exe=d;mscoree=d;mshtml=d;ucrtbase,concrt140,msvcp140,msvcp140_1,msvcp140_2,msvcp140_atomic_wait,msvcp140_codecvt_ids,vcamp140,vccorlib140,vcomp140,vcruntime140,vcruntime140_1,vcruntime140_threads=n,b";

/// Chromium messages that mark a start that died under emulation.
pub const FAILURE_MARKERS: [&str; 3] = [
    "GPU process isn't usable",
    "GPU process launch failed",
    "Network service crashed",
];

/// Where everything lives and how the VM is sized.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Layout {
    pub root: PathBuf,
    pub app: PathBuf,
    pub prefix: PathBuf,
    pub wine: PathBuf,
    pub mem_mib: u32,
    pub gpu: bool,
    /// Leave V8's JIT compilers on. Under FEX they crash Spark.
    pub jit: bool,
    /// Loopback port inside the VM for Spark's Node inspector.
    pub inspect_port: u16,
    /// Extra environment for the guest, for example FEX settings.
    pub guest_env: Vec<(String, String)>,
    /// Extra arguments for Spark, for example Chromium switches.
    pub spark_args: Vec<String>,
}

/// Parse `KEY=VALUE` for the guest environment. Keys must be plain shell names.
pub fn parse_guest_env(pair: &str) -> Result<(String, String), String> {
    let (key, value) = pair
        .split_once('=')
        .ok_or_else(|| format!("expected KEY=VALUE, got {pair:?}"))?;
    let mut chars = key.chars();
    let valid = chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '_');
    if !valid {
        return Err(format!("invalid environment variable name {key:?}"));
    }
    Ok((key.to_owned(), value.to_owned()))
}

impl Layout {
    pub fn tmp(&self) -> PathBuf {
        self.root.join("tmp")
    }
    pub fn launch_log(&self) -> PathBuf {
        self.tmp().join("launch.log")
    }
    /// Directory put first on PATH inside the VM. It holds `xdg-open`.
    pub fn guest_tools(&self) -> PathBuf {
        self.tmp().join("arm-host-tools")
    }
    pub fn spool(&self) -> PathBuf {
        self.tmp().join("open-requests")
    }
    /// Present while a `--stop` is in progress, so the starter does not retry.
    pub fn stop_flag(&self) -> PathBuf {
        self.tmp().join("spark-arm.stop")
    }
    pub fn lock_file(&self) -> PathBuf {
        self.tmp().join("spark-arm.lock")
    }
    /// Private directory for links on their way into the VM.
    pub fn deliveries(&self) -> PathBuf {
        self.tmp().join("deliveries")
    }
    pub fn wineserver(&self) -> PathBuf {
        self.wine.with_file_name("wineserver")
    }
}

/// Quote one word for a POSIX shell.
pub fn sh_quote(word: &str) -> String {
    format!("'{}'", word.replace('\'', r"'\''"))
}

fn path_str(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

/// Environment and working directory shared by every command run in the VM.
fn guest_preamble(layout: &Layout) -> String {
    let extra: String = layout
        .guest_env
        .iter()
        .map(|(key, value)| format!("export {key}={}; ", sh_quote(value)))
        .collect();
    format!(
        "{extra}export SPARK_ROOT={root} WINEPREFIX={prefix} WINEDEBUG=-all WINEDLLOVERRIDES={ovr} PATH={tools}:\"$PATH\"; cd {app} || exit 1; ",
        root = sh_quote(&path_str(&layout.root)),
        prefix = sh_quote(&path_str(&layout.prefix)),
        ovr = sh_quote(DLL_OVERRIDES),
        tools = sh_quote(&path_str(&layout.guest_tools())),
        app = sh_quote(&path_str(&layout.app)),
    )
}

/// Arguments Spark itself receives. Links never go here: a command line is
/// readable by other processes, so they are handed over once Spark is ready.
pub fn spark_args(layout: &Layout) -> Vec<String> {
    let mut args = Vec::new();
    if !layout.gpu {
        args.push("--disable-gpu".to_owned());
    }
    if !layout.jit {
        args.push("--js-flags=--jitless".to_owned());
    }
    // The launcher hands links to Spark through this port. See `inspect.rs`.
    args.push(format!("--inspect=127.0.0.1:{}", layout.inspect_port));
    args.extend(layout.spark_args.iter().cloned());
    args
}

fn wine_line(layout: &Layout) -> String {
    let mut line = format!(
        "{} {}",
        sh_quote(&path_str(&layout.wine)),
        sh_quote(SPARK_EXE)
    );
    for arg in spark_args(layout) {
        line.push(' ');
        line.push_str(&sh_quote(&arg));
    }
    line
}

/// Script for the first launch. Output goes to the launch log, because muvm
/// does not pass stdout back reliably.
pub fn start_script(layout: &Layout) -> String {
    format!(
        "{}exec {} </dev/null >{} 2>&1",
        guest_preamble(layout),
        wine_line(layout),
        sh_quote(&path_str(&layout.launch_log()))
    )
}

/// Script that asks this prefix's Wine server to stop, which closes Spark.
pub fn stop_script(layout: &Layout) -> String {
    format!(
        "{}exec {} -k </dev/null >/dev/null 2>&1",
        guest_preamble(layout),
        sh_quote(&path_str(&layout.wineserver()))
    )
}

/// The `-e` value that marks a muvm process as belonging to this root.
pub fn root_marker(root: &Path) -> String {
    format!("SPARK_ROOT={}", root.display())
}

/// Full muvm argument list (without the program name) for one guest command.
/// `-m` is required: without the merged rootfs Wine cannot load kernel32.
/// When a VM is already up, muvm runs the command inside it and returns.
pub fn muvm_args(layout: &Layout, command: &[String]) -> Vec<String> {
    let mut args = vec![
        "-m".to_owned(),
        format!("--mem={}", layout.mem_mib),
        "-e".to_owned(),
        root_marker(&layout.root),
        "--".to_owned(),
    ];
    args.extend(command.iter().cloned());
    args
}

/// Guest command that runs an x86_64 shell script under FEX.
pub fn fex_command(script: &str) -> Vec<String> {
    vec!["FEXBash".to_owned(), "-c".to_owned(), script.to_owned()]
}

/// Flag that makes the launcher act as the in-VM delivery helper.
pub const GUEST_DELIVER_FLAG: &str = "--guest-deliver";

/// Guest command that hands the link in `request` to Spark and writes the
/// outcome to `result`. The launcher is a native binary, so no FEX is involved.
pub fn deliver_command(layout: &Layout, exe: &Path, request: &Path, result: &Path) -> Vec<String> {
    vec![
        path_str(exe),
        GUEST_DELIVER_FLAG.to_owned(),
        layout.inspect_port.to_string(),
        path_str(request),
        path_str(result),
    ]
}

fn is_muvm(cmdline: &[String]) -> bool {
    cmdline.first().is_some_and(|program| {
        Path::new(program).file_name().and_then(|n| n.to_str()) == Some("muvm")
    })
}

/// True when a process command line is a muvm VM started for this root.
pub fn is_spark_vm(cmdline: &[String], root: &Path) -> bool {
    is_muvm(cmdline) && cmdline.contains(&root_marker(root))
}

/// True for a muvm VM that belongs to something else. muvm runs one VM per
/// user, so a start would land inside that VM and return at once.
pub fn is_other_vm(cmdline: &[String], root: &Path) -> bool {
    is_muvm(cmdline) && !cmdline.contains(&root_marker(root))
}

/// Split the NUL-separated contents of `/proc/<pid>/cmdline`.
pub fn parse_cmdline(raw: &[u8]) -> Vec<String> {
    raw.split(|byte| *byte == 0)
        .filter(|part| !part.is_empty())
        .map(|part| String::from_utf8_lossy(part).into_owned())
        .collect()
}

/// What this invocation should do.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// Nothing is running: start the VM and Spark.
    Start,
    /// A VM for this root is up: hand the link to the running Spark.
    Forward,
    /// Another launcher holds the lock but its VM is not up yet.
    Starting,
}

/// `lock_acquired`: this process took the launcher lock.
/// `vm_running`: a muvm process for this root exists.
pub fn decide_mode(lock_acquired: bool, vm_running: bool) -> Mode {
    match (vm_running, lock_acquired) {
        (true, _) => Mode::Forward,
        (false, true) => Mode::Start,
        (false, false) => Mode::Starting,
    }
}

/// Log line Spark prints once its main process has finished starting.
pub const READY_MARKER: &str = "Application bootstrap is completed";

/// Retry settings for a failed start.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RetryPolicy {
    /// Total starts allowed, including the first.
    pub max_attempts: u32,
    /// A start that is not ready after this long is hung and gets stopped.
    pub ready_timeout: Duration,
    /// Wait before the next start. Relaunching too fast fails again.
    pub pause: Duration,
}

/// How one run of the VM ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RunOutcome {
    /// The log showed [`READY_MARKER`].
    pub ready: bool,
    /// muvm exited with status 0.
    pub exit_ok: bool,
    /// The log shows a known Chromium crash.
    pub failure_marker: bool,
    /// The launcher stopped a start that never became ready.
    pub timed_out: bool,
    /// Someone ran `--stop` during this run.
    pub stop_requested: bool,
}

/// A start failed when the run ended before Spark became ready, unless a
/// stop was requested. Once Spark is ready, any exit is the end of a session.
pub fn start_failed(outcome: &RunOutcome) -> bool {
    !outcome.ready && !outcome.stop_requested
}

/// `attempt` counts from 1.
pub fn should_retry(policy: &RetryPolicy, attempt: u32, outcome: &RunOutcome) -> bool {
    start_failed(outcome) && attempt < policy.max_attempts
}

/// True when a start has run past the ready timeout without becoming ready.
pub fn is_hung(policy: &RetryPolicy, ready: bool, elapsed: Duration) -> bool {
    !ready && elapsed >= policy.ready_timeout
}

pub fn has_failure_marker(log: &str) -> bool {
    FAILURE_MARKERS.iter().any(|marker| log.contains(marker))
}

fn contains_ignore_case(haystack: &[u8], needle: &[u8]) -> bool {
    haystack
        .windows(needle.len())
        .any(|window| window.eq_ignore_ascii_case(needle))
}

/// The same guard as `run-spark.sh`: an update can put back the imports that
/// crash under Wine. `shim_exists` reports whether a DLL sits beside the app.
pub fn foundation_problem(foundation: &[u8], shim_exists: impl Fn(&str) -> bool) -> Option<String> {
    if contains_ignore_case(foundation, b"USERENV.dll") {
        return Some(
            "Foundation.dll still imports USERENV.dll. Reapply shims/patch-foundation.py and shims/patch-iphlpapi.py."
                .to_owned(),
        );
    }
    for shim in ["sprkenv.dll", "sprkiphl.dll"] {
        if contains_ignore_case(foundation, shim.as_bytes()) && !shim_exists(shim) {
            return Some(format!(
                "missing {shim} beside the app. Run shims/build.sh."
            ));
        }
    }
    if contains_ignore_case(foundation, b"sprkenv.dll")
        && contains_ignore_case(foundation, b"IPHLPAPI.DLL")
    {
        return Some(
            "Foundation.dll still imports IPHLPAPI.DLL. Run shims/patch-iphlpapi.py.".to_owned(),
        );
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn layout() -> Layout {
        Layout {
            root: "/r".into(),
            app: "/r/app".into(),
            prefix: "/r/prefix".into(),
            wine: "/r/runtime/usr/bin/wine".into(),
            mem_mib: 5000,
            gpu: false,
            jit: false,
            inspect_port: 9229,
            guest_env: Vec::new(),
            spark_args: Vec::new(),
        }
    }

    const POLICY: RetryPolicy = RetryPolicy {
        max_attempts: 3,
        ready_timeout: Duration::from_secs(300),
        pause: Duration::from_secs(10),
    };

    const CRASHED: RunOutcome = RunOutcome {
        ready: false,
        exit_ok: false,
        failure_marker: true,
        timed_out: false,
        stop_requested: false,
    };

    #[test]
    fn quotes_single_quotes() {
        assert_eq!(sh_quote("it's"), r"'it'\''s'");
        assert_eq!(sh_quote("$(x) `y`"), "'$(x) `y`'");
    }

    #[test]
    fn muvm_args_use_merged_rootfs_and_mark_the_root() {
        let args = muvm_args(&layout(), &fex_command("true"));
        assert_eq!(
            args,
            [
                "-m",
                "--mem=5000",
                "-e",
                "SPARK_ROOT=/r",
                "--",
                "FEXBash",
                "-c",
                "true"
            ]
        );
    }

    #[test]
    fn start_script_disables_gpu_and_logs_to_file() {
        let script = start_script(&layout());
        assert!(script.contains("WINEPREFIX='/r/prefix'"));
        assert!(script.contains("PATH='/r/tmp/arm-host-tools':\"$PATH\""));
        assert!(script.contains("cd '/r/app' || exit 1; "));
        assert!(script.ends_with(
            "exec '/r/runtime/usr/bin/wine' 'Spark Desktop.exe' '--disable-gpu' '--js-flags=--jitless' '--inspect=127.0.0.1:9229' </dev/null >'/r/tmp/launch.log' 2>&1"
        ));
    }

    #[test]
    fn guest_env_is_validated_and_exported_first() {
        assert_eq!(
            parse_guest_env("FEX_SMCCHECKS=full"),
            Ok(("FEX_SMCCHECKS".to_owned(), "full".to_owned()))
        );
        assert!(parse_guest_env("NOVALUE").is_err());
        assert!(parse_guest_env("A;reboot=1").is_err());
        assert!(parse_guest_env("=1").is_err());
        let mut layout = layout();
        layout.guest_env = vec![("A_B".to_owned(), "it's".to_owned())];
        assert!(start_script(&layout).starts_with(r"export A_B='it'\''s'; export SPARK_ROOT="));
    }

    #[test]
    fn gpu_and_jit_flags_drop_the_safe_defaults() {
        let mut layout = layout();
        layout.gpu = true;
        layout.jit = true;
        layout.inspect_port = 9300;
        assert_eq!(spark_args(&layout), ["--inspect=127.0.0.1:9300"]);
        layout.spark_args = vec!["--x".to_owned()];
        assert_eq!(spark_args(&layout), ["--inspect=127.0.0.1:9300", "--x"]);
    }

    #[test]
    fn deliver_command_runs_the_launcher_natively() {
        let command = deliver_command(
            &layout(),
            Path::new("/r/.build/spark-arm"),
            Path::new("/r/tmp/deliveries/1.url"),
            Path::new("/r/tmp/deliveries/1.result"),
        );
        assert_eq!(
            command,
            [
                "/r/.build/spark-arm",
                "--guest-deliver",
                "9229",
                "/r/tmp/deliveries/1.url",
                "/r/tmp/deliveries/1.result"
            ]
        );
    }

    #[test]
    fn stop_script_targets_this_wineserver() {
        assert!(stop_script(&layout()).contains("exec '/r/runtime/usr/bin/wineserver' -k"));
    }

    #[test]
    fn detects_only_muvm_for_this_root() {
        let ours = parse_cmdline(b"/usr/bin/muvm\0-m\0-e\0SPARK_ROOT=/r\0--\0FEXBash\0");
        assert!(is_spark_vm(&ours, Path::new("/r")));
        assert!(!is_other_vm(&ours, Path::new("/r")));
        assert!(is_other_vm(&ours, Path::new("/other")));
        assert!(!is_spark_vm(&ours, Path::new("/other")));
        let other_vm = parse_cmdline(b"muvm\0-m\0--\0steam\0");
        assert!(!is_spark_vm(&other_vm, Path::new("/r")));
        assert!(is_other_vm(&other_vm, Path::new("/r")));
        let not_muvm = parse_cmdline(b"bash\0-c\0muvm -e SPARK_ROOT=/r\0SPARK_ROOT=/r\0");
        assert!(!is_spark_vm(&not_muvm, Path::new("/r")));
        assert!(!is_other_vm(&not_muvm, Path::new("/r")));
        assert!(!is_spark_vm(&[], Path::new("/r")));
    }

    #[test]
    fn mode_follows_lock_and_vm() {
        assert_eq!(decide_mode(true, false), Mode::Start);
        assert_eq!(decide_mode(false, true), Mode::Forward);
        // A VM started by hand has no launcher lock, but still gets forwards.
        assert_eq!(decide_mode(true, true), Mode::Forward);
        assert_eq!(decide_mode(false, false), Mode::Starting);
    }

    #[test]
    fn retries_failed_starts_up_to_the_limit() {
        assert!(should_retry(&POLICY, 1, &CRASHED));
        assert!(should_retry(&POLICY, 2, &CRASHED));
        assert!(!should_retry(&POLICY, 3, &CRASHED));
        let hung = RunOutcome {
            failure_marker: false,
            timed_out: true,
            ..CRASHED
        };
        assert!(should_retry(&POLICY, 1, &hung));
    }

    #[test]
    fn does_not_retry_a_session_that_became_ready() {
        // Chromium logs GPU errors in sessions that work, so the marker
        // alone is not a failure once Spark is ready.
        let session = RunOutcome {
            ready: true,
            ..CRASHED
        };
        assert!(!should_retry(&POLICY, 1, &session));
    }

    #[test]
    fn does_not_retry_a_requested_stop() {
        let stopped = RunOutcome {
            stop_requested: true,
            ..CRASHED
        };
        assert!(!should_retry(&POLICY, 1, &stopped));
    }

    #[test]
    fn an_exit_before_ready_is_a_failed_start_even_when_clean() {
        // muvm returns 0 at once when it hands the command to another VM.
        let instant = RunOutcome {
            exit_ok: true,
            failure_marker: false,
            ..CRASHED
        };
        assert!(start_failed(&instant));
    }

    #[test]
    fn hung_only_before_ready_and_after_the_timeout() {
        assert!(!is_hung(&POLICY, false, Duration::from_secs(299)));
        assert!(is_hung(&POLICY, false, Duration::from_secs(300)));
        assert!(!is_hung(&POLICY, true, Duration::from_secs(900)));
    }

    #[test]
    fn finds_failure_markers() {
        assert!(has_failure_marker(
            "x\nGPU process isn't usable. Goodbye.\n"
        ));
        assert!(!has_failure_marker("Application bootstrap is completed"));
    }

    #[test]
    fn foundation_guard_matches_run_spark() {
        let all = |_: &str| true;
        let none = |_: &str| false;
        assert!(foundation_problem(b"..userenv.DLL..", all).is_some());
        assert!(foundation_problem(b"sprkenv.dll sprkiphl.dll", none).is_some());
        assert!(foundation_problem(b"sprkenv.dll iphlpapi.dll", all).is_some());
        assert_eq!(foundation_problem(b"sprkenv.dll sprkiphl.dll", all), None);
        // Older builds import neither USERENV nor the shims.
        assert_eq!(foundation_problem(b"IPHLPAPI.DLL", none), None);
    }
}
