# SPDX-License-Identifier: MIT
# https://github.com/m-kru/vhdl-amba5
# Copyright (c) 2026 Michal Kruszewski
#
# Python interface for APB Serial Bridge.
#
# This module provides a SerialBridge class for controlling the APB serial bridge
# hardware component via any serial interface (UART, SPI, socket, etc.).
#
# Requirements:
#   - The 'iface' object must provide read(n) and write(bytes) methods
#   - The 'addr_byte_count' must match the VHDL generic ADDR_BYTE_COUNT
#
# Example usage:
#   import serial
#   from apb import SerialBridge, SLVERR
#
#   # Using pyserial
#   ser = serial.Serial('/dev/ttyUSB0', 115200)
#   bridge = SerialBridge(addr_byte_count=2, iface=ser)
#
#   # Single register access
#   value = bridge.read(0x10)
#   bridge.write(0x10, 0xDEADBEEF)
#
#   # Block transfers (sequential addresses)
#   data = bridge.block_read(0x00, count=4)  # Read 4 registers
#   bridge.block_write(0x00, [0x11, 0x22, 0x33, 0x44])
#
#   # Cyclic transfers (same address, for FIFOs)
#   fifo_data = bridge.cyclic_read(0x100, count=8)
#   bridge.cyclic_write(0x100, [0xAA, 0xBB, 0xCC])
#
#   # Read-Modify-Write (atomic bit manipulation)
#   bridge.rmw(0x10, data=0xFF, mask=0x0F)  # Set lower nibble to 0xF
#

class SLVERR(Exception):
    """Exception raised when APB completer returns SLVERR.
    
    This indicates the target peripheral rejected the transaction.
    Common causes include invalid address, access violation, or
    peripheral-specific error conditions.
    """
    pass


class SerialBridge:
    """Python interface for APB Serial Bridge hardware component.
    
    This class provides methods to perform APB transactions over a serial
    interface. It supports single read/write, block transfers, cyclic
    transfers (for FIFOs), and atomic read-modify-write operations.
    
    Transaction Types:
        - READ (0b000): Single register read
        - WRITE (0b001): Single register write
        - BLOCK_READ (0b010): Read sequential registers
        - BLOCK_WRITE (0b011): Write sequential registers
        - CYCLIC_READ (0b100): Read same address multiple times (FIFO)
        - CYCLIC_WRITE (0b101): Write same address multiple times (FIFO)
        - RMW (0b110): Atomic read-modify-write
    
    Attributes:
        addr_byte_count: Number of address bytes (1-4), must match VHDL generic
        iface: Serial interface object with read(n) and write(bytes) methods
    """
    
    _READ = 0b000
    _WRITE = 0b001
    _BLOCK_READ = 0b010
    _BLOCK_WRITE = 0b011
    _CYCLIC_READ = 0b100
    _CYCLIC_WRITE = 0b101
    _RMW = 0b110

    def __init__(self, addr_byte_count, iface):
        """Initialize the SerialBridge.
        
        Args:
            addr_byte_count: Number of address bytes (1-4). Must match the
                ADDR_BYTE_COUNT generic configured in the VHDL serial bridge.
            iface: Serial interface object. Must provide:
                - read(n): Read n bytes, returns bytes-like object
                - write(data): Write bytes to interface
                Examples: pyserial.Serial, socket, or mock object for testing.
        
        Raises:
            AssertionError: If addr_byte_count is out of valid range.
        """
        assert 1 <= addr_byte_count <= 4, "addr_byte_count must be 1-4"
        self.addr_byte_count = addr_byte_count
        self.iface = iface

    def _build_addr_bytes(self, addr):
        """Build address byte sequence for transmission."""
        addr_bytes = []
        for i in reversed(range(self.addr_byte_count)):
            addr_bytes.append((addr >> i * 8) & 0xFF)
        return addr_bytes

    def _check_addr_range(self, addr):
        """Validate address is within configured range."""
        max_addr = 2 ** (8 * self.addr_byte_count) - 1
        assert 0 <= addr <= max_addr, f"addr {addr:#x} overrange (max {max_addr:#x})"

    def read(self, addr):
        """Read data from a single register.
        
        Args:
            addr: Register address (not byte address). The address is
                automatically shifted left by 2 to convert to byte address.
        
        Returns:
            32-bit unsigned integer value read from the register.
        
        Raises:
            SLVERR: If the APB completer returns an error.
            AssertionError: If address is out of range.
        """
        addr <<= 2  # Shift to byte address

        self._check_addr_range(addr)

        tx_buf = [self._READ << 5]
        tx_buf.extend(self._build_addr_bytes(addr))

        self.iface.write(bytes(tx_buf))

        status = self.iface.read(1)[0]
        if (status & 0x80) != 0:
            raise SLVERR(f"read: addr {addr:#08X}")

        rx_buf = self.iface.read(4)
        return int.from_bytes(rx_buf, byteorder='big')

    def write(self, addr, data):
        """Write data to a single register.
        
        Args:
            addr: Register address (not byte address). The address is
                automatically shifted left by 2 to convert to byte address.
            data: 32-bit data value to write.
        
        Raises:
            SLVERR: If the APB completer returns an error.
            AssertionError: If address or data is out of range.
        """
        addr <<= 2  # Shift to byte address

        self._check_addr_range(addr)
        assert 0 <= data <= 0xFFFFFFFF, f"data overrange"

        tx_buf = [self._WRITE << 5]
        tx_buf.extend(self._build_addr_bytes(addr))
        for i in reversed(range(4)):
            tx_buf.append((data >> i * 8) & 0xFF)

        self.iface.write(bytes(tx_buf))

        status = self.iface.read(1)[0]
        if (status & 0x80) != 0:
            raise SLVERR(f"write: addr {addr:#08X}, data {data:#08X}")

    def block_read(self, addr, count):
        """Read multiple sequential registers.
        
        Performs a block read starting at the given address. Each subsequent
        read increments the address by 4 (one 32-bit register).
        
        Args:
            addr: Starting register address (not byte address).
            count: Number of 32-bit registers to read (1-256).
        
        Returns:
            List of 32-bit unsigned integer values.
        
        Raises:
            SLVERR: If any APB transaction returns an error.
            AssertionError: If parameters are out of range.
        """
        addr <<= 2  # Shift to byte address

        self._check_addr_range(addr)
        assert 1 <= count <= 256, "count must be 1-256"

        # Request byte: type[7:5] | size[4:0] (size = count - 1)
        tx_buf = [(self._BLOCK_READ << 5) | ((count - 1) & 0x1F)]
        tx_buf.extend(self._build_addr_bytes(addr))

        self.iface.write(bytes(tx_buf))

        results = []
        for _ in range(count):
            status = self.iface.read(1)[0]
            if (status & 0x80) != 0:
                raise SLVERR(f"block_read: addr {addr:#08X}")

            rx_buf = self.iface.read(4)
            results.append(int.from_bytes(rx_buf, byteorder='big'))

        return results

    def block_write(self, addr, data_list):
        """Write multiple sequential registers.
        
        Performs a block write starting at the given address. Each subsequent
        write increments the address by 4 (one 32-bit register).
        
        Args:
            addr: Starting register address (not byte address).
            data_list: List of 32-bit data values to write (1-256 items).
        
        Raises:
            SLVERR: If any APB transaction returns an error.
            AssertionError: If parameters are out of range.
        """
        addr <<= 2  # Shift to byte address
        count = len(data_list)

        self._check_addr_range(addr)
        assert 1 <= count <= 256, "data_list length must be 1-256"

        # Request byte: type[7:5] | size[4:0] (size = count - 1)
        tx_buf = [(self._BLOCK_WRITE << 5) | ((count - 1) & 0x1F)]
        tx_buf.extend(self._build_addr_bytes(addr))

        # Append all data bytes
        for data in data_list:
            assert 0 <= data <= 0xFFFFFFFF, f"data overrange"
            for i in reversed(range(4)):
                tx_buf.append((data >> i * 8) & 0xFF)

        self.iface.write(bytes(tx_buf))

        # Read status bytes for each transfer
        for idx, data in enumerate(data_list):
            status = self.iface.read(1)[0]
            if (status & 0x80) != 0:
                raise SLVERR(f"block_write: addr {addr + idx*4:#08X}, data {data:#08X}")

    def cyclic_read(self, addr, count):
        """Read from the same address multiple times (for FIFOs).
        
        Performs multiple reads from the same address without incrementing.
        Useful for reading from FIFO registers.
        
        Args:
            addr: Register address (not byte address).
            count: Number of reads to perform (1-256).
        
        Returns:
            List of 32-bit unsigned integer values.
        
        Raises:
            SLVERR: If any APB transaction returns an error.
            AssertionError: If parameters are out of range.
        """
        addr <<= 2  # Shift to byte address

        self._check_addr_range(addr)
        assert 1 <= count <= 256, "count must be 1-256"

        # Request byte: type[7:5] | size[4:0] (size = count - 1)
        tx_buf = [(self._CYCLIC_READ << 5) | ((count - 1) & 0x1F)]
        tx_buf.extend(self._build_addr_bytes(addr))

        self.iface.write(bytes(tx_buf))

        results = []
        for _ in range(count):
            status = self.iface.read(1)[0]
            if (status & 0x80) != 0:
                raise SLVERR(f"cyclic_read: addr {addr:#08X}")

            rx_buf = self.iface.read(4)
            results.append(int.from_bytes(rx_buf, byteorder='big'))

        return results

    def cyclic_write(self, addr, data_list):
        """Write to the same address multiple times (for FIFOs).
        
        Performs multiple writes to the same address without incrementing.
        Useful for writing to FIFO registers.
        
        Args:
            addr: Register address (not byte address).
            data_list: List of 32-bit data values to write (1-256 items).
        
        Raises:
            SLVERR: If any APB transaction returns an error.
            AssertionError: If parameters are out of range.
        """
        addr <<= 2  # Shift to byte address
        count = len(data_list)

        self._check_addr_range(addr)
        assert 1 <= count <= 256, "data_list length must be 1-256"

        # Request byte: type[7:5] | size[4:0] (size = count - 1)
        tx_buf = [(self._CYCLIC_WRITE << 5) | ((count - 1) & 0x1F)]
        tx_buf.extend(self._build_addr_bytes(addr))

        # Append all data bytes
        for data in data_list:
            assert 0 <= data <= 0xFFFFFFFF, f"data overrange"
            for i in reversed(range(4)):
                tx_buf.append((data >> i * 8) & 0xFF)

        self.iface.write(bytes(tx_buf))

        # Read status bytes for each transfer
        for idx, data in enumerate(data_list):
            status = self.iface.read(1)[0]
            if (status & 0x80) != 0:
                raise SLVERR(f"cyclic_write: addr {addr:#08X}, data {data:#08X}")

    def rmw(self, addr, data, mask):
        """Atomic read-modify-write operation.
        
        Performs an atomic RMW transaction:
            new_value = (old_value & ~mask) | (data & mask)
        
        This is useful for setting or clearing specific bits without
        affecting other bits in the register.
        
        Args:
            addr: Register address (not byte address).
            data: Data value containing bits to set.
            mask: Mask indicating which bits to modify (1 = modify, 0 = preserve).
        
        Raises:
            SLVERR: If the read or write phase returns an error.
            AssertionError: If parameters are out of range.
        
        Example:
            # Set bits [3:0] to 0xF, preserve all other bits
            bridge.rmw(0x10, data=0x0000000F, mask=0x0000000F)
            
            # Clear bit 7
            bridge.rmw(0x10, data=0x00000000, mask=0x00000080)
        """
        addr <<= 2  # Shift to byte address

        self._check_addr_range(addr)
        assert 0 <= data <= 0xFFFFFFFF, f"data overrange"
        assert 0 <= mask <= 0xFFFFFFFF, f"mask overrange"

        # Build request: type | addr | data (4 bytes) | mask (4 bytes)
        tx_buf = [self._RMW << 5]
        tx_buf.extend(self._build_addr_bytes(addr))

        # Data bytes (MSB first)
        for i in reversed(range(4)):
            tx_buf.append((data >> i * 8) & 0xFF)

        # Mask bytes (MSB first)
        for i in reversed(range(4)):
            tx_buf.append((mask >> i * 8) & 0xFF)

        self.iface.write(bytes(tx_buf))

        # Read phase status
        status = self.iface.read(1)[0]
        if (status & 0x80) != 0:
            raise SLVERR(f"rmw read phase: addr {addr:#08X}")

        # Write phase status
        status = self.iface.read(1)[0]
        if (status & 0x80) != 0:
            raise SLVERR(f"rmw write phase: addr {addr:#08X}")