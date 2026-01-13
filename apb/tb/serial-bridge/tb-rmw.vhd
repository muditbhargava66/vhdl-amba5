library ieee;
  use ieee.std_logic_1164.all;
  use ieee.numeric_std.all;

library lapb;
  use lapb.apb.all;
  use lapb.checker.all;
  use lapb.mock_completer.all;
  use lapb.serial_bridge.all;


entity tb_rmw is
end entity;


architecture test of tb_rmw is

  constant CLK_PERIOD : time := 10 ns;

  signal clk : std_logic := '0';

  signal sb : serial_bridge_t := init(ADDR_BYTE_COUNT => 1);

  signal ibyte : std_logic_vector(7 downto 0);
  signal ibyte_valid, obyte_ready : std_logic := '0';

  signal ck : checker_t := init;
  signal com : completer_out_t := init;

  -- Initialize memory with known values
  signal completer_data : data_array_t(0 to 3) := (
    x"12345678", x"AABBCCDD", x"DEADBEEF", x"CAFEBABE"
  );
  signal mc : mock_completer_t(memory(0 to 3)) := init(memory_size => 4);

begin

  clk <= not clk after CLK_PERIOD / 2;


  interface_checker : process (clk) is
  begin
    if rising_edge(clk) then
      ck <= clock(ck, sb.apb_req, com);
    end if;
  end process;


  DUT : process (clk) is
  begin
    if rising_edge(clk) then
      sb <= clock(sb, ibyte, ibyte_valid, obyte_ready, com);
    end if;
  end process;


  Completer : process (clk) is
  begin
    if rising_edge(clk) then
      clock(mc, sb.apb_req, com);
    end if;
  end process;


  Stall_Checker : process (clk) is
    variable cnt : natural := 0;
  begin
    if rising_edge(clk) then
      cnt := cnt + 1;
      if cnt = 200 then
        report "bridge stall" severity failure;
      end if;
    end if;
  end process;


  Main : process is

    -- Perform RMW transaction
    -- Formula: Memory[addr] = (Memory[addr] & ~mask) | (data & mask)
    procedure rmw (
      address     : integer;
      data        : std_logic_vector(31 downto 0);
      mask        : std_logic_vector(31 downto 0);
      want        : std_logic_vector(31 downto 0);
      delay       : integer := 0
    ) is
      constant addr : std_logic_vector(7 downto 0) := std_logic_vector(to_unsigned(address, 8));
    begin
      -- Request byte (Type = "110" = RMW)
      ibyte <= b"11000000";
      ibyte_valid <= '1';
      wait until rising_edge(clk) and ibyte_valid = '1' and sb.ibyte_ready = '1';
      ibyte_valid <= '0';
      wait for delay * CLK_PERIOD;

      -- Address byte
      ibyte <= addr;
      ibyte_valid <= '1';
      wait until rising_edge(clk) and ibyte_valid = '1' and sb.ibyte_ready = '1';
      ibyte_valid <= '0';
      wait for delay * CLK_PERIOD;

      -- Data bytes (MSB first)
      for i in 3 downto 0 loop
        ibyte <= data(i * 8 + 7 downto i * 8);
        ibyte_valid <= '1';
        wait until rising_edge(clk) and ibyte_valid = '1' and sb.ibyte_ready = '1';
        ibyte_valid <= '0';
        wait for delay * CLK_PERIOD;
      end loop;

      -- Mask bytes (MSB first)
      for i in 3 downto 0 loop
        ibyte <= mask(i * 8 + 7 downto i * 8);
        ibyte_valid <= '1';
        wait until rising_edge(clk) and ibyte_valid = '1' and sb.ibyte_ready = '1';
        ibyte_valid <= '0';
        wait for delay * CLK_PERIOD;
      end loop;

      -- Read status byte
      obyte_ready <= '1';
      wait until rising_edge(clk) and obyte_ready = '1' and sb.obyte_valid = '1';
      assert sb.obyte = b"00000000"
        report "invalid read status byte, got " & to_string(sb.obyte) & ", want ""00000000"""
        severity failure;
      obyte_ready <= '0';
      wait for delay * CLK_PERIOD;

      -- Write status byte
      obyte_ready <= '1';
      wait until rising_edge(clk) and obyte_ready = '1' and sb.obyte_valid = '1';
      assert sb.obyte = b"00000000"
        report "invalid write status byte, got " & to_string(sb.obyte) & ", want ""00000000"""
        severity failure;
      obyte_ready <= '0';
      wait for delay * CLK_PERIOD;

      -- Verify memory content
      assert mc.memory(address / 4) = want
        report "RMW failed: got " & to_hstring(mc.memory(address / 4)) & ", want " & to_hstring(want)
        severity failure;

    end procedure rmw;

  begin
    wait for 5 * CLK_PERIOD;

    -- Initialize memory content
    mc.memory <= completer_data;
    wait for 2 * CLK_PERIOD;

    -- Test 1: Set lower byte only (mask = 0x000000FF)
    -- Original: 0x12345678, Data: 0x000000AA, Mask: 0x000000FF
    -- Result:   0x123456AA
    rmw(0, x"000000AA", x"000000FF", x"123456AA");

    -- Test 2: Set upper 16 bits (mask = 0xFFFF0000)
    -- Original: 0xAABBCCDD, Data: 0x11220000, Mask: 0xFFFF0000
    -- Result:   0x1122CCDD
    rmw(4, x"11220000", x"FFFF0000", x"1122CCDD");

    -- Test 3: Flip specific bits (mask = 0x0F0F0F0F)
    -- Original: 0xDEADBEEF, Data: 0x00000000, Mask: 0x0F0F0F0F
    -- Result:   0xD0A0B0E0
    rmw(8, x"00000000", x"0F0F0F0F", x"D0A0B0E0");

    -- Test 4: Full write (mask = 0xFFFFFFFF)
    -- Original: 0xCAFEBABE, Data: 0x11223344, Mask: 0xFFFFFFFF
    -- Result:   0x11223344
    rmw(12, x"11223344", x"FFFFFFFF", x"11223344", 1);

    report "All RMW tests passed!" severity note;
    wait for 3 * CLK_PERIOD;
    std.env.finish;
  end process;

end architecture;
