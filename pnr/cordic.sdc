# Copyright 2026 Daniel Tyukov
# SPDX-License-Identifier: Apache-2.0
#
# Timing constraints for the CORDIC accelerator, used by both the PnR flow and
# signoff so neither falls back to a generic SDC.
#
# CLOCK_PERIOD comes from the LibreLane config, so the period here is read from the
# environment rather than hard-coded, and the two cannot disagree.

set clk_period $::env(CLOCK_PERIOD)
set clk_port   [get_ports clk_i]

create_clock -name clk -period $clk_period $clk_port

# 5 percent of the period for clock uncertainty, which is a normal allowance for a
# design of this size before a real CTS result is available.
set_clock_uncertainty [expr {$clk_period * 0.05}] clk

# The accelerator is a subordinate on Croc's OBI crossbar. Both the request into it
# and the response out of it cross the interconnect, so allow a quarter period each
# way rather than pretending the ports are at the die edge.
set io_delay [expr {$clk_period * 0.25}]

set all_in  [all_inputs]
set data_in [list]
foreach p $all_in {
  if {[get_full_name $p] ne [get_full_name [lindex $clk_port 0]]} {
    lappend data_in $p
  }
}

set_input_delay  $io_delay -clock clk $data_in
set_output_delay $io_delay -clock clk [all_outputs]

# A real driver on the inputs and a real load on the outputs. Without these the
# tool assumes an ideal zero-slew source and an open-circuit output.
set_driving_cell -lib_cell sg13g2_inv_4 -pin Y $data_in
set_load 0.02 [all_outputs]

# rst_ni is asynchronous, released well away from any clock edge.
set_false_path -from [get_ports rst_ni]

# The observation ports exist for the testbench and the documentation figures and
# are left unconnected in a real integration, so they must not constrain timing.
foreach pat {dbg_stage_valid_o dbg_iter_valid_o dbg_iter_idx_o
             dbg_iter_x_o dbg_iter_y_o dbg_iter_z_o} {
  set ports [get_ports -quiet ${pat}*]
  if {[llength $ports] > 0} {
    set_false_path -to $ports
  }
}

set_max_transition [expr {$clk_period * 0.15}] [current_design]
