import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

NAVY = "#1f3a5f"
BLUE = "#2f6db3"
GREEN = "#2e7d32"
ORANGE = "#c25e00"
GREY = "#5f6b7a"
LIGHT = "#eef4fb"
LIGHT2 = "#f4f7f2"
WHITE = "#ffffff"


def box(ax, x, y, w, h, title, sub="", fc=LIGHT, ec=BLUE, title_size=12, sub_size=9):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                       linewidth=1.5, edgecolor=ec, facecolor=fc)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h - 0.28, title, ha="center", va="top",
            fontsize=title_size, fontweight="bold", color=NAVY)
    if sub:
        ax.text(x + w / 2, y + h - 0.68, sub, ha="center", va="top",
                fontsize=sub_size, color=GREY, linespacing=1.3)


def arrow(ax, p1, p2, label="", color=BLUE, style="-|>", ls="-", lw=1.8, text_offset=(0, 0.18), fs=9):
    a = FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=14,
                        linewidth=lw, color=color, linestyle=ls,
                        shrinkA=4, shrinkB=4)
    ax.add_patch(a)
    if label:
        mx, my = (p1[0] + p2[0]) / 2 + text_offset[0], (p1[1] + p2[1]) / 2 + text_offset[1]
        ax.text(mx, my, label, ha="center", va="bottom", fontsize=fs,
                color=color, bbox=dict(boxstyle="round,pad=0.18", fc=WHITE, ec="none", alpha=0.9))


def architecture():
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    ax.set_xlim(0, 16); ax.set_ylim(0, 9); ax.axis("off")
    ax.text(0.3, 8.65, "hid-as-rx — macOS + X-Plane 11 + INAV SITL architecture",
            fontsize=18, fontweight="bold", color=NAVY)
    ax.text(0.3, 8.28, "All processes run on the same macOS host; arrows show TCP/UDP ports and protocols.",
            fontsize=10.5, color=GREY)

    # left side
    box(ax, 0.4, 3.8, 2.5, 1.8, "HID controller", "radio / gamepad\nUSB HID", fc="#fff7e8", ec=ORANGE)
    box(ax, 3.2, 3.8, 2.8, 1.8, "hid2msp.py", "pygame + MSP v1\n16 RC channels", fc=LIGHT2, ec=GREEN)

    # SITL
    box(ax, 7.2, 2.1, 4.2, 4.7, "INAV SITL 9.0.0", "flight-controller logic\nreceiver → mixer → PID", fc="#e8f0fb", ec=NAVY, title_size=13)
    ax.plot([7.45, 11.15], [5.78, 5.78], color="#b8c4d4", lw=1.0)
    ax.text(7.45, 5.48, "UART1  :5760   Configurator", fontsize=9.4, color=NAVY, va="top", family="monospace")
    ax.text(7.45, 5.10, "UART2  :5761   HITL plugin", fontsize=9.4, color=NAVY, va="top", family="monospace")
    ax.text(7.45, 4.72, "UART3  :5762   RC bridge", fontsize=9.4, color=NAVY, va="top", family="monospace")
    ax.text(7.45, 4.34, "UART4  :5763   MSP DisplayPort", fontsize=9.4, color=NAVY, va="top", family="monospace")
    ax.text(7.45, 3.55, "TCP server on localhost\nMSP v1 / MSP v2", fontsize=9.0, color=GREY, va="top", linespacing=1.4)

    # right side
    box(ax, 12.0, 3.0, 3.4, 2.3, "X-Plane 11.55", "INAV Surfwing aircraft\nphysics + rendering", fc="#fdf2e9", ec=ORANGE, title_size=13)
    box(ax, 12.0, 6.0, 3.4, 1.35, "INAV HITL plugin", "mac.xpl (x86_64)\nsensors + control + OSD", fc=LIGHT, ec=BLUE)
    box(ax, 12.0, 1.1, 3.4, 0.95, "OSD display port", "MSP DisplayPort (UART4)\nSITL-side OSD canvas", fc="#f3f0fa", ec="#6a4c93")

    # top
    box(ax, 7.2, 7.35, 4.2, 0.8, "INAV Configurator 9.0.0", "setup / CLI / receiver / mixer", fc=LIGHT2, ec=GREEN, title_size=12, sub_size=8.6)

    # arrows
    ax.annotate("", xy=(3.2, 4.7), xytext=(2.9, 4.7),
                arrowprops=dict(arrowstyle="-|>", color=ORANGE, lw=1.8, shrinkA=3, shrinkB=3))

    ax.annotate("", xy=(7.2, 4.7), xytext=(6.0, 4.7),
                arrowprops=dict(arrowstyle="-|>", color=GREEN, lw=1.8, shrinkA=3, shrinkB=3))
    ax.text(6.6, 4.9, "TCP 5762\nMSP RC", ha="center", fontsize=8.5, color=GREEN)

    ax.annotate("", xy=(7.5, 6.8), xytext=(7.5, 7.35),
                arrowprops=dict(arrowstyle="-|>", color=GREEN, lw=1.8, shrinkA=3, shrinkB=3))
    ax.text(7.65, 7.0, "5760 / MSP", ha="left", fontsize=8.8, color=GREEN)

    ax.annotate("", xy=(12.0, 6.55), xytext=(11.4, 5.55),
                arrowprops=dict(arrowstyle="-|>", color=BLUE, lw=1.8, shrinkA=3, shrinkB=3))

    ax.annotate("", xy=(13.7, 6.0), xytext=(13.7, 5.3),
                arrowprops=dict(arrowstyle="<|-|>", color=BLUE, lw=1.6, shrinkA=3, shrinkB=3))
    ax.text(13.9, 5.65, "XPLM datarefs\n+ OSD draw", ha="left", fontsize=8.5, color=BLUE)

    ax.annotate("", xy=(12.0, 1.6), xytext=(11.4, 2.6),
                arrowprops=dict(arrowstyle="-|>", color="#6a4c93", lw=1.5, ls="--", shrinkA=3, shrinkB=3))

    # side notes
    ax.text(0.4, 3.25, "CH1-4 sticks\nCH5 knob zone\nCH6 SWC → WP\nCH7 SWB → ARM\nCH8 knob 6-mode\nCH9 launch",
            fontsize=8.8, color=GREY, va="top", linespacing=1.35)
    ax.text(0.4, 1.6, "Mode/arm mapping: SITL aux table\nKnob→CH8 mapping: hid2msp JSON",
            fontsize=8.6, color=GREY, va="top", linespacing=1.4)

    fig.savefig("docs/architecture.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def sequence():
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    ax.set_xlim(0, 16); ax.set_ylim(0, 9); ax.axis("off")
    ax.text(0.3, 8.65, "Runtime sequence — one RC frame (~50 Hz)",
            fontsize=18, fontweight="bold", color=NAVY)
    ax.text(0.3, 8.28, "Startup: Configurator loads params → X-Plane loads INAV Surfwing → plugin connects 5761 → bridge connects 5762.",
            fontsize=10, color=GREY)

    parts = [("HID", 1.2), ("hid2msp.py", 3.8), ("INAV SITL", 6.6), ("HITL plugin", 10.0), ("X-Plane 11", 13.2)]
    top, bottom = 7.7, 0.9
    for name, x in parts:
        ax.add_patch(Rectangle((x - 0.95, top - 0.45), 1.9, 0.55, facecolor=NAVY, edgecolor=NAVY))
        ax.text(x, top - 0.17, name, ha="center", va="center", color=WHITE, fontsize=10, fontweight="bold")
        ax.plot([x, x], [bottom, top - 0.45], color="#b8c4d4", lw=1.2, ls="--")

    def msg(y, x1, x2, text, color=BLUE, ls="-"):
        ax.annotate("", xy=(x2, y), xytext=(x1, y),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=1.8, linestyle=ls, shrinkA=3, shrinkB=3))
        ax.text((x1 + x2) / 2, y + 0.12, text, ha="center", va="bottom", fontsize=9,
                color=color, bbox=dict(boxstyle="round,pad=0.18", fc=WHITE, ec="none", alpha=0.92))

    msg(7.0, 1.2, 3.8, "1. poll sticks / switches", ORANGE)
    msg(6.55, 3.8, 6.6, "2. MSP_SET_RAW_RC\nCH1..CH9", GREEN)
    msg(6.1, 6.6, 10.0, "3. MSP_SIMULATOR\ncontrols + OSD + flags", BLUE)
    msg(5.65, 10.0, 13.2, "4. yoke / throttle + OSD", BLUE)
    msg(5.2, 13.2, 10.0, "5. attitude / sensors", ORANGE, ls="--")
    msg(4.75, 10.0, 6.6, "6. sensor MSP", ORANGE)

    # loop frame
    ax.add_patch(Rectangle((0.5, 4.3), 13.5, 3.0, fill=False, edgecolor="#8a9bb0", lw=1.2, ls=":"))
    ax.text(0.65, 4.15, "loop @ 50 Hz", fontsize=9, color=GREY, style="italic")

    # arm and failsafe notes
    ax.add_patch(Rectangle((0.6, 2.6), 4.4, 1.0, facecolor="#fff7e8", edgecolor=ORANGE, lw=1.2))
    ax.text(0.8, 3.35, "ARM: SWB high → CH7 2000", fontsize=9.5, color=ORANGE, fontweight="bold")
    ax.text(0.8, 3.02, "SITL checks arm flags; OSD shows state.", fontsize=8.6, color=GREY)
    ax.add_patch(Rectangle((5.4, 2.6), 4.8, 1.0, facecolor="#f3f0fa", edgecolor="#6a4c93", lw=1.2))
    ax.text(5.6, 3.35, "FAILSAFE: no RC frames > 200 ms", fontsize=9.5, color="#6a4c93", fontweight="bold")
    ax.text(5.6, 3.02, "Bridge crash/disconnect → INAV FS (RTH).", fontsize=8.6, color=GREY)

    ax.text(0.6, 1.6, "Mode channel CH8: knob → 1000 / 1200 / 1400 / 1600 / 1800 / 2000\n"
                      "SWC → CH6 high = NAV WP (aux 8 28 1 1950 2050)\n"
                      "CH9 = 2000 → NAV LAUNCH permanently enabled",
            fontsize=9.2, color=NAVY, linespacing=1.5)

    fig.savefig("docs/sequence.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)




def startup():
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    ax.set_xlim(0, 16); ax.set_ylim(0, 9); ax.axis("off")
    ax.text(0.3, 8.65, "Startup sequence — bring up the components",
            fontsize=18, fontweight="bold", color=NAVY)
    ax.text(0.3, 8.28, "SITL must be running before the plugin/bridge connect; start X-Plane and SITL in either order.",
            fontsize=10, color=GREY)

    parts = [("User", 1.1), ("X-Plane 11", 3.6), ("HITL plugin", 6.0), ("INAV SITL", 8.6), ("hid2msp.py", 11.3), ("Configurator", 14.0)]
    top, bottom = 7.7, 0.9
    for name, x in parts:
        ax.add_patch(Rectangle((x - 0.9, top - 0.45), 1.8, 0.55, facecolor=NAVY, edgecolor=NAVY))
        ax.text(x, top - 0.17, name, ha="center", va="center", color=WHITE, fontsize=9.5, fontweight="bold")
        ax.plot([x, x], [bottom, top - 0.45], color="#b8c4d4", lw=1.2, ls="--")

    def msg(y, x1, x2, text, color=BLUE, ls="-"):
        ax.annotate("", xy=(x2, y), xytext=(x1, y),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=1.7, linestyle=ls, shrinkA=3, shrinkB=3))
        ax.text((x1 + x2) / 2, y + 0.1, text, ha="center", va="bottom", fontsize=8.7,
                color=color, bbox=dict(boxstyle="round,pad=0.16", fc=WHITE, ec="none", alpha=0.92))

    msg(7.0, 1.1, 3.6, "1. load INAV Surfwing", ORANGE)
    msg(6.55, 3.6, 6.0, "2. load mac.xpl", ORANGE)
    msg(6.1, 1.1, 8.6, "3. start SITL with plane.bin", GREEN)
    msg(5.65, 8.6, 8.6, "4. open 5760 / 5761 / 5762 / 5763", NAVY)
    msg(5.2, 14.0, 8.6, "5. TCP 5760: params (optional)", GREEN, ls="--")
    msg(4.75, 11.3, 8.6, "6. TCP 5762: MSP RC", GREEN)
    msg(4.3, 6.0, 8.6, "7. TCP 5761: MSP SIM", BLUE)
    msg(3.85, 1.1, 3.6, "8. arm / fly", ORANGE)

    ax.add_patch(Rectangle((0.5, 1.7), 6.1, 0.9, facecolor="#fff7e8", edgecolor=ORANGE, lw=1.1))
    ax.text(0.7, 2.35, "Important: SWB low before starting hid2msp.py", fontsize=9.2, color=ORANGE, fontweight="bold")
    ax.text(0.7, 2.05, "CH7 must read 1000 (disarmed) in Configurator.", fontsize=8.5, color=GREY)
    ax.add_patch(Rectangle((7.0, 1.7), 6.0, 0.9, facecolor="#f3f0fa", edgecolor="#6a4c93", lw=1.1))
    ax.text(7.2, 2.35, "One client per UART", fontsize=9.2, color="#6a4c93", fontweight="bold")
    ax.text(7.2, 2.05, "Do not point two apps at the same port.", fontsize=8.5, color=GREY)

    fig.savefig("docs/startup.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    sequence()
    startup()
    print("wrote docs/architecture.png, docs/sequence.png, docs/startup.png")
