# Requirements

## Software

We currently support all major operating systems (Linux, macOS, Windows). The software assumes that you installed [Python](https://www.python.org) `3.12` or newer.

## Hardware

This API is designed to interact with the ICOtronic system and thus only reasonably works with this system connected.

To get a complete experience, even for development, you need:

- A **CAN interface** (usually either [PCAN-USB](https://www.peak-system.com/PCAN-USB.199.0.html) or the RevPi CAN Module)
- The proper drivers:
  - For PCAN-USB you can find a description on how to install and set up the drivers for [Linux](https://mytoolit.github.io/ICOtronic/#introduction:section:pcan-driver:linux), [macOS](https://mytoolit.github.io/ICOtronic/#introduction:section:pcan-driver:macos) and [Windows](https://mytoolit.github.io/ICOtronic/#introduction:section:pcan-driver:windows) in the [documentation of the ICOtronic package](https://mytoolit.github.io/ICOtronic/#pcan-driver).
