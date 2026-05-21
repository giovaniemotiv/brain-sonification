{pkgs}: {
  deps = [
    pkgs.xvfb-run
    pkgs.python312Packages.tkinter
    pkgs.python312Full
    pkgs.tk
    pkgs.tcl
  ];
}
