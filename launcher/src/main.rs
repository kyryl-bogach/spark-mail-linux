use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use clap::Parser;
use spark_arm::links::{self, HostTarget};
use spark_arm::vm::{self, Layout, Mode, RetryPolicy, RunOutcome};
use spark_arm::{desktop, inspect};

/// Run Spark Desktop on an ARM Linux host through muvm, FEX-Emu and Wine.
///
/// With Spark already running, the URL (or a plain second launch) is handed
/// to the running instance instead of starting a second one.
#[derive(Parser, Debug)]
#[command(version)]
struct Cli {
    /// Spark callback, deep link or mailto URL to hand to Spark.
    url: Option<String>,

    /// Installation directory holding app/, prefix/, runtime/ and tmp/.
    #[arg(long, env = "SPARK_ROOT")]
    root: PathBuf,

    /// Application directory [default: ROOT/app].
    #[arg(long, env = "SPARK_APP")]
    app: Option<PathBuf>,

    /// Wine prefix [default: ROOT/prefix].
    #[arg(long, env = "SPARK_PREFIX")]
    prefix: Option<PathBuf>,

    /// x86_64 wine binary outside the FEX rootfs [default: ROOT/runtime/usr/bin/wine].
    #[arg(long, env = "SPARK_WINE")]
    wine: Option<PathBuf>,

    /// VM memory limit in MiB. The VM takes memory only as it needs it.
    #[arg(long, env = "SPARK_VM_MEM", default_value_t = 6000)]
    mem: u32,

    /// Leave GPU acceleration on. It is unstable under emulation.
    #[arg(long, env = "SPARK_GPU")]
    gpu: bool,

    /// Leave V8's JIT compilers on. Spark crashes with them under FEX.
    #[arg(long, env = "SPARK_JIT")]
    jit: bool,

    /// Port inside the VM for Spark's Node inspector, which takes forwarded links.
    #[arg(long, env = "SPARK_INSPECT_PORT", default_value_t = 9229)]
    inspect_port: u16,

    /// Starts allowed when Spark dies during startup, including the first.
    #[arg(long, env = "SPARK_START_ATTEMPTS", default_value_t = 3)]
    attempts: u32,

    /// Seconds to wait before a retry.
    #[arg(long, default_value_t = 10)]
    retry_pause: u64,

    /// Seconds a start may take to become ready before it is stopped and retried.
    #[arg(long, env = "SPARK_READY_TIMEOUT", default_value_t = 300)]
    ready_timeout: u64,

    /// Extra KEY=VALUE for the environment inside the VM. Repeatable.
    #[arg(long = "guest-env", value_name = "KEY=VALUE", value_parser = vm::parse_guest_env)]
    guest_env: Vec<(String, String)>,

    /// Extra argument for Spark, such as a Chromium switch. Repeatable.
    #[arg(long = "spark-arg", value_name = "ARG", allow_hyphen_values = true)]
    spark_args: Vec<String>,

    /// muvm binary.
    #[arg(long, env = "SPARK_MUVM", default_value = "muvm")]
    muvm: PathBuf,

    /// Stop Spark by stopping this prefix's Wine server.
    #[arg(long, conflicts_with = "url")]
    stop: bool,

    /// Write the desktop entries and register Spark's URL schemes.
    #[arg(long, conflicts_with_all = ["url", "stop"])]
    install_desktop: bool,
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs())
}

/// Launcher log. It never receives a URL, only schemes and counts.
struct Log(PathBuf);

impl Log {
    fn line(&self, message: &str) {
        eprintln!("spark-arm: {message}");
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&self.0) {
            let _ = writeln!(file, "{} {message}", now_secs());
        }
    }
}

fn absolute(path: &Path) -> Result<PathBuf, String> {
    fs::canonicalize(path).map_err(|e| format!("{}: {e}", path.display()))
}

fn layout(cli: &Cli) -> Result<Layout, String> {
    let root = absolute(&cli.root)?;
    let app = absolute(&cli.app.clone().unwrap_or_else(|| root.join("app")))?;
    // Wine fills an empty prefix on the first launch.
    let prefix = cli.prefix.clone().unwrap_or_else(|| root.join("prefix"));
    fs::create_dir_all(&prefix).map_err(|e| format!("{}: {e}", prefix.display()))?;
    let prefix = absolute(&prefix)?;
    // Not canonicalized: wine may be a symlink and must keep its own directory.
    let wine = cli
        .wine
        .clone()
        .unwrap_or_else(|| root.join("runtime/usr/bin/wine"));
    if !wine.is_file() {
        return Err(format!(
            "no wine at {}. Extract it from the FEX rootfs (see INSTALLATION.md).",
            wine.display()
        ));
    }
    if !app.join(vm::SPARK_EXE).is_file() {
        return Err(format!("missing {} in {}", vm::SPARK_EXE, app.display()));
    }
    Ok(Layout {
        root,
        app,
        prefix,
        wine,
        mem_mib: cli.mem,
        gpu: cli.gpu,
        jit: cli.jit,
        inspect_port: cli.inspect_port,
        guest_env: cli.guest_env.clone(),
        spark_args: cli.spark_args.clone(),
    })
}

fn check_foundation(layout: &Layout) -> Result<(), String> {
    let foundation = layout.app.join(
        "resources/app.asar.unpacked/node_modules/@readdle/sparkcore-win/bin/Release/SparkCore.bundle/Foundation.dll",
    );
    let Ok(bytes) = fs::read(&foundation) else {
        return Ok(());
    };
    match vm::foundation_problem(&bytes, |shim| layout.app.join(shim).is_file()) {
        Some(problem) => Err(problem),
        None => Ok(()),
    }
}

fn any_process(matches: impl Fn(&[String]) -> bool) -> bool {
    let Ok(entries) = fs::read_dir("/proc") else {
        return false;
    };
    entries.filter_map(Result::ok).any(|entry| {
        fs::read(entry.path().join("cmdline")).is_ok_and(|raw| matches(&vm::parse_cmdline(&raw)))
    })
}

fn vm_running(root: &Path) -> bool {
    any_process(|cmdline| vm::is_spark_vm(cmdline, root))
}

/// muvm's own messages, kept because `launch.log` only exists once the guest runs.
fn muvm_log(layout: &Layout) -> PathBuf {
    layout.tmp().join("muvm.log")
}

fn muvm(cli: &Cli, layout: &Layout, guest_command: &[String]) -> Command {
    let mut command = Command::new(&cli.muvm);
    command
        .args(vm::muvm_args(layout, guest_command))
        .current_dir(&layout.app)
        .stdin(Stdio::null());
    command
}

/// The guest `xdg-open` is a symlink to this binary inside ROOT/tmp.
fn install_guest_tools(layout: &Layout) -> Result<(), String> {
    let dir = layout.guest_tools();
    fs::create_dir_all(&dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    let link = dir.join("xdg-open");
    let exe = std::env::current_exe().map_err(|e| format!("cannot find own path: {e}"))?;
    if fs::read_link(&link).is_ok_and(|target| target == exe) {
        return Ok(());
    }
    let _ = fs::remove_file(&link);
    std::os::unix::fs::symlink(&exe, &link).map_err(|e| format!("{}: {e}", link.display()))
}

fn open_on_host(target: &str, log: &Log) {
    let Some(target) = links::classify_target(target) else {
        log.line("refused an open request that is neither a web link nor a file");
        return;
    };
    let argument = match &target {
        HostTarget::Web(url) => url.clone(),
        HostTarget::File(path) if path.exists() => path.to_string_lossy().into_owned(),
        HostTarget::File(_) => {
            log.line("refused an open request for a file that does not exist");
            return;
        }
    };
    let spawned = Command::new("xdg-open")
        .arg(argument)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn();
    match spawned {
        Ok(mut child) => {
            log.line(&format!("opened a {} on the host", target.kind()));
            thread::spawn(move || child.wait());
        }
        Err(e) => log.line(&format!("host xdg-open failed: {e}")),
    }
}

fn log_contains(layout: &Layout, needle: &str) -> bool {
    fs::read(layout.launch_log()).is_ok_and(|log| String::from_utf8_lossy(&log).contains(needle))
}

/// Deliver with retries: right after the ready marker Spark may not listen yet.
fn deliver_when_listening(
    cli: &Cli,
    layout: &Layout,
    url: Option<&str>,
    wait: Duration,
) -> Result<(), String> {
    let deadline = Instant::now() + wait;
    loop {
        match deliver(cli, layout, url) {
            Ok(()) => return Ok(()),
            Err(e) if Instant::now() > deadline || !vm_running(&layout.root) => return Err(e),
            Err(_) => thread::sleep(Duration::from_secs(5)),
        }
    }
}

fn run_vm_once(
    cli: &Cli,
    layout: &Layout,
    policy: &RetryPolicy,
    pending_url: &mut Option<&str>,
    log: &Log,
) -> Result<RunOutcome, String> {
    links::clear(&layout.spool()).map_err(|e| format!("spool: {e}"))?;
    let _ = fs::remove_file(layout.launch_log());
    let muvm_stderr = File::create(muvm_log(layout)).map_err(|e| format!("muvm log: {e}"))?;
    let started = Instant::now();
    let mut child = muvm(cli, layout, &vm::fex_command(&vm::start_script(layout)))
        .stdout(Stdio::null())
        .stderr(muvm_stderr)
        .spawn()
        .map_err(|e| format!("cannot run {}: {e}", cli.muvm.display()))?;
    let mut ready = false;
    let mut stopped_at: Option<Instant> = None;
    let mut ticks = 0u32;
    let status = loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|e| format!("waiting for muvm: {e}"))?
        {
            break status;
        }
        for target in links::drain(&layout.spool()).unwrap_or_default() {
            open_on_host(&target, log);
        }
        ticks += 1;
        // Every 3 s: look for readiness, then for a hung start.
        if !ready && stopped_at.is_none() && ticks.is_multiple_of(10) {
            if log_contains(layout, vm::READY_MARKER) {
                ready = true;
                log.line(&format!(
                    "Spark is ready after {} s",
                    started.elapsed().as_secs()
                ));
                if let Some(url) = pending_url.take() {
                    let wait = Duration::from_secs(60);
                    match deliver_when_listening(cli, layout, Some(url), wait) {
                        Ok(()) => log.line("handed the link to Spark"),
                        Err(e) => log.line(&format!("could not hand the link to Spark: {e}")),
                    }
                }
            } else if vm::is_hung(policy, false, started.elapsed()) {
                stopped_at = Some(Instant::now());
                log.line("Spark did not become ready in time: stopping this start");
                let stop = vm::fex_command(&vm::stop_script(layout));
                if let Err(e) = run_in_vm(cli, layout, &stop) {
                    log.line(&format!("could not stop the hung start: {e}"));
                }
            }
        }
        // A start that ignores the stop is killed so the retry can run.
        if stopped_at.is_some_and(|at| at.elapsed() > Duration::from_secs(30)) {
            log.line("the hung start ignored the stop: killing the VM");
            let _ = child.kill();
            break child.wait().map_err(|e| format!("waiting for muvm: {e}"))?;
        }
        thread::sleep(Duration::from_millis(300));
    };
    Ok(RunOutcome {
        ready: ready || log_contains(layout, vm::READY_MARKER),
        exit_ok: status.success(),
        failure_marker: fs::read(layout.launch_log())
            .is_ok_and(|log| vm::has_failure_marker(&String::from_utf8_lossy(&log))),
        timed_out: stopped_at.is_some(),
        stop_requested: layout.stop_flag().exists(),
    })
}

fn start(cli: &Cli, layout: &Layout, url: Option<&str>, log: &Log) -> Result<(), String> {
    check_foundation(layout)?;
    install_guest_tools(layout)?;
    if any_process(|cmdline| vm::is_other_vm(cmdline, &layout.root)) {
        return Err(
            "another muvm VM is running. muvm runs one VM per user, so close it before starting Spark."
                .to_owned(),
        );
    }
    let policy = RetryPolicy {
        max_attempts: cli.attempts.max(1),
        ready_timeout: Duration::from_secs(cli.ready_timeout),
        pause: Duration::from_secs(cli.retry_pause),
    };
    let _ = fs::remove_file(layout.stop_flag());
    let mut pending_url = url;
    for attempt in 1..=policy.max_attempts {
        if layout.stop_flag().exists() {
            log.line("stop requested: not starting again");
            return Ok(());
        }
        log.line(&format!("starting Spark, attempt {attempt}"));
        let started = Instant::now();
        let outcome = run_vm_once(cli, layout, &policy, &mut pending_url, log)?;
        log.line(&format!(
            "Spark exited after {} s (ready: {}, clean exit: {}, crash marker: {}, hung: {})",
            started.elapsed().as_secs(),
            outcome.ready,
            outcome.exit_ok,
            outcome.failure_marker,
            outcome.timed_out
        ));
        if !vm::start_failed(&outcome) {
            return Ok(());
        }
        if !vm::should_retry(&policy, attempt, &outcome) {
            break;
        }
        thread::sleep(policy.pause);
    }
    Err(format!(
        "Spark failed to start {} times. See {} and {}",
        policy.max_attempts,
        layout.launch_log().display(),
        muvm_log(layout).display()
    ))
}

/// Run one command inside the running VM. muvm returns at once, without the
/// command's output or exit status.
fn run_in_vm(cli: &Cli, layout: &Layout, guest_command: &[String]) -> Result<(), String> {
    let status = muvm(cli, layout, guest_command)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|e| format!("cannot run {}: {e}", cli.muvm.display()))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("muvm exited with {status}"))
    }
}

/// Hand a link (or a plain "show the window") to the running Spark.
///
/// The link travels in an owner-only file, not on a command line, and the
/// helper inside the VM answers through a second file.
fn deliver(cli: &Cli, layout: &Layout, url: Option<&str>) -> Result<(), String> {
    let exe = std::env::current_exe().map_err(|e| format!("cannot find own path: {e}"))?;
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    let id = format!("{nanos}-{}", std::process::id());
    let request = layout.deliveries().join(format!("{id}.url"));
    let result = layout.deliveries().join(format!("{id}.result"));
    links::write_private(&request, url.unwrap_or_default())
        .map_err(|e| format!("delivery file: {e}"))?;
    let command = vm::deliver_command(layout, &exe, &request, &result);
    let outcome = run_in_vm(cli, layout, &command).and_then(|()| {
        let deadline = Instant::now() + Duration::from_secs(45);
        loop {
            // The helper writes the result under a temporary name first.
            if let Ok(text) = fs::read_to_string(&result) {
                return if text.trim() == "ok" {
                    Ok(())
                } else {
                    Err(text.trim().to_owned())
                };
            }
            if Instant::now() > deadline {
                return Err("no answer from the helper inside the VM".to_owned());
            }
            thread::sleep(Duration::from_millis(200));
        }
    });
    let _ = fs::remove_file(&request);
    let _ = fs::remove_file(&result);
    outcome
}

fn install_desktop(layout: &Layout) -> Result<(), String> {
    let exe = std::env::current_exe().map_err(|e| format!("cannot find own path: {e}"))?;
    let data_home = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/share")))
        .ok_or("neither XDG_DATA_HOME nor HOME is set")?;
    let dir = data_home.join("applications");
    fs::create_dir_all(&dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    let unsafe_path = || "the launcher or root path has characters a desktop entry cannot carry";
    let entries = [
        (
            desktop::LAUNCHER_FILE,
            desktop::launcher_entry(&exe, &layout.root).ok_or_else(unsafe_path)?,
        ),
        (
            desktop::HANDLER_FILE,
            desktop::handler_entry(&exe, &layout.root).ok_or_else(unsafe_path)?,
        ),
    ];
    for (name, content) in entries {
        let path = dir.join(name);
        fs::write(&path, content).map_err(|e| format!("{}: {e}", path.display()))?;
        println!("Installed {}", path.display());
    }
    // Optional tool: the entries work without the cache.
    let _ = Command::new("update-desktop-database").arg(&dir).status();
    for mime in desktop::handler_mime_types() {
        let status = Command::new("xdg-mime")
            .args(["default", desktop::HANDLER_FILE, &mime])
            .status()
            .map_err(|e| format!("xdg-mime: {e}"))?;
        if !status.success() {
            return Err(format!("xdg-mime failed for {mime}"));
        }
    }
    println!(
        "Registered {} URL schemes",
        desktop::handler_mime_types().len()
    );
    Ok(())
}

fn run(cli: &Cli) -> Result<(), String> {
    let layout = layout(cli)?;
    fs::create_dir_all(layout.tmp()).map_err(|e| format!("{}: {e}", layout.tmp().display()))?;
    if cli.install_desktop {
        return install_desktop(&layout);
    }
    let log = Log(layout.tmp().join("spark-arm.log"));
    let url = match &cli.url {
        Some(url) => {
            let scheme = links::spark_scheme(url).ok_or("unsupported Spark URL scheme")?;
            log.line(&format!("received a {scheme} link"));
            Some(url.as_str())
        }
        None => None,
    };
    if cli.stop {
        // The flag also stops a launcher that is waiting between attempts.
        File::create(layout.stop_flag()).map_err(|e| format!("stop flag: {e}"))?;
        if !vm_running(&layout.root) {
            println!("Spark is not running.");
            return Ok(());
        }
        return run_in_vm(cli, &layout, &vm::fex_command(&vm::stop_script(&layout)));
    }
    let lock = File::create(layout.lock_file()).map_err(|e| format!("lock file: {e}"))?;
    let mut locked = lock.try_lock().is_ok();
    // A link can arrive while another launcher is between attempts.
    let deadline = Instant::now() + Duration::from_secs(180);
    loop {
        match vm::decide_mode(locked, vm_running(&layout.root)) {
            Mode::Start => return start(cli, &layout, url, &log),
            Mode::Forward => {
                // Spark may still be starting: keep trying until it listens.
                let wait = Duration::from_secs(cli.ready_timeout);
                let outcome = deliver_when_listening(cli, &layout, url, wait);
                log.line(match &outcome {
                    Ok(()) => "Spark is running: handed over to it",
                    Err(_) => "Spark is running, but the hand-over failed",
                });
                return outcome.map_err(|e| format!("could not reach the running Spark: {e}"));
            }
            Mode::Starting if url.is_none() => {
                log.line("another launcher is already starting Spark");
                return Ok(());
            }
            Mode::Starting if Instant::now() > deadline => {
                return Err("Spark did not come up in time to take the link".to_owned());
            }
            Mode::Starting => {
                thread::sleep(Duration::from_secs(2));
                locked = lock.try_lock().is_ok();
            }
        }
    }
}

/// Runs inside the VM as `xdg-open`: queue the target for the host.
fn guest_open() -> ExitCode {
    let target = std::env::args_os()
        .nth(1)
        .and_then(|arg| arg.into_string().ok());
    let (Some(target), Some(root)) = (target, std::env::var_os("SPARK_ROOT")) else {
        eprintln!("xdg-open: needs a UTF-8 target and SPARK_ROOT");
        return ExitCode::from(2);
    };
    let spool = PathBuf::from(root).join("tmp/open-requests");
    match links::enqueue(&spool, &target) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("xdg-open: {e}");
            ExitCode::FAILURE
        }
    }
}

/// Runs inside the VM: `--guest-deliver PORT REQUEST RESULT`. Reads the link,
/// removes the file, hands the link to Spark and records the outcome.
fn guest_deliver(args: &[String]) -> ExitCode {
    let [port, request, result] = args else {
        eprintln!(
            "spark-arm: {} needs PORT REQUEST RESULT",
            vm::GUEST_DELIVER_FLAG
        );
        return ExitCode::from(2);
    };
    let outcome = port
        .parse::<u16>()
        .map_err(|e| e.to_string())
        .and_then(|port| {
            let url = fs::read_to_string(request).map_err(|e| e.to_string())?;
            let _ = fs::remove_file(request);
            inspect::deliver(port, (!url.is_empty()).then_some(url.as_str()))
                .map_err(|e| e.to_string())
        });
    let text = match &outcome {
        Ok(()) => "ok".to_owned(),
        Err(e) => format!("error: {e}"),
    };
    // Rename so the host never reads a half-written answer.
    let partial = format!("{result}.part");
    let written = links::write_private(Path::new(&partial), &text)
        .and_then(|()| fs::rename(&partial, result));
    if outcome.is_ok() && written.is_ok() {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn main() -> ExitCode {
    // args_os: a non-UTF-8 argument must not panic before the mode is known.
    let args: Vec<String> = std::env::args_os()
        .skip(1)
        .map(|arg| arg.to_string_lossy().into_owned())
        .collect();
    if args.first().map(String::as_str) == Some(vm::GUEST_DELIVER_FLAG) {
        return guest_deliver(&args[1..]);
    }
    let invoked_as = std::env::args_os().next().map(PathBuf::from);
    if invoked_as.as_deref().and_then(Path::file_name) == Some("xdg-open".as_ref()) {
        return guest_open();
    }
    match run(&Cli::parse()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("spark-arm: {message}");
            ExitCode::FAILURE
        }
    }
}
