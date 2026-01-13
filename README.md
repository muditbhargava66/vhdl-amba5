[![Tests](https://github.com/m-kru/vhdl-amba5/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/m-kru/vhdl-amba5/actions?query=master)

# vhdl-amba5

Library with VHDL cores implementing Advanced Microcontroller Bus Architecture 5 (AMBA5) specifications such as APB, AHB, and AXI.
Currently only APB is implemented.
All VHDL files are compatible with the standard revision 2008 and have no external dependencies.
All the code simulates correctly with ghdl, nvc, questa and xsim simulators.

## Implemented Cores

| Core | Description |
|------|-------------|
| `apb.vhd` | Main APB package with types and helper functions |
| `bfm.vhd` | Bus Functional Model for simulation |
| `checker.vhd` | Protocol compliance checker |
| `crossbar.vhd` | NxM Crossbar interconnect |
| `shared-bus.vhd` | Shared bus interconnect |
| `cdc-bridge.vhd` | Clock Domain Crossing bridge |
| `serial-bridge.vhd` | Serial-to-APB bridge (UART/SPI) |
| `mock-completer.vhd` | Simple memory completer for testing |

## Prerequisites

- **Tcl 8.5+** - Required for HBS build system
- **Simulator** - One of: ghdl, nvc, questa, or xsim
- **Python 3** (optional) - For using the Python serial bridge interface

## Running Tests

The internal build system is [HBS](https://github.com/m-kru/hbs).

```bash
# Set your simulator (ghdl, nvc, questa, or xsim)
export HBS_TOOL=ghdl

# Run all APB tests
./scripts/hbs test apb

# Run a specific test
./scripts/hbs apb::bfm::tb-write
./scripts/hbs apb::serial-bridge::tb-rmw

# List all available tests
./scripts/hbs list-tb apb
```

However, you can use any build system - simply copy required source files.

## Python Interface

A Python interface for the serial bridge is available at `apb/sw/python/apb.py`.
See the docstrings in that file for usage examples and API documentation.

## License

MIT License - see source files for details.
