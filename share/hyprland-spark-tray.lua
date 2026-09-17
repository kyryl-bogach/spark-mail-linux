-- Wine renders Spark's tray icon as a small floating tile when the session has
-- no XEmbed tray host. Keep only the empty floating explorer helper out of the
-- visible workspace; Spark's main window uses class "spark desktop.exe".
o.window({
  class = "^explorer[.]exe$",
  title = "^$",
  xwayland = true,
  float = true,
}, {
  workspace = "special:spark-tray silent",
  no_initial_focus = true,
  no_focus = true,
  no_anim = true,
  decorate = false,
})
