# display

A lightweight GUI for positioning monitors on X11 Linux, similar to Windows Display Settings. Drag your monitors where you want them and click Apply.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![X11](https://img.shields.io/badge/display-X11-orange)

## Features

- Parses your current monitor layout from `xrandr`
- Drag monitors to reposition them
- Edge snapping (edges, alignment, center) with overlap prevention
- Preview the exact `xrandr` command before applying
- Optional post-apply hook for wallpaper or other scripts

## Requirements

- Python 3.10+
- Tkinter (usually bundled with Python; may need to be installed separately)
- X11 with `xrandr`

### Installing Tkinter

| Distro | Command |
|--------|---------|
| Arch | `sudo pacman -S tk` |
| Debian/Ubuntu | `sudo apt install python3-tk` |
| Fedora | `sudo dnf install python3-tkinter` |

## Usage

```sh
python display.py
```

Or make it executable and add it to your PATH:

```sh
chmod +x display.py
ln -s /path/to/display.py ~/.local/bin/display
```

## Post-apply hook

If `~/.config/display/post-apply` exists and is executable, it runs after every Apply. Useful for resetting wallpaper or running other commands after a layout change.

```sh
mkdir -p ~/.config/display
cat > ~/.config/display/post-apply << 'EOF'
#!/bin/sh
xwallpaper --zoom ~/Pictures/wallpaper.png
EOF
chmod +x ~/.config/display/post-apply
```

## Auto-launch on monitor hotplug

If you use [xplugd](https://github.com/troglobit/xplugd), add this to your `~/.xplugrc`:

```sh
#!/bin/sh

[ "$1" != "display" ] && exit 0

if [ "$3" = "disconnected" ]; then
    xrandr --output "$2" --off
    exit 0
fi

# Skip if GUI is already managing positions
[ -f /tmp/display-gui.lock ] && exit 0

# Default: new monitor to the right, then open GUI
LAPTOP=$(xrandr --query | grep ' connected' | head -1 | awk '{print $1}')
xrandr --output "$LAPTOP" --auto --pos 0x0 \
       --output "$2" --auto --primary --right-of "$LAPTOP"
DISPLAY=:0 display &
```

## Limitations

- X11 only (no Wayland support)
- Does not change resolution or refresh rate (only position)
