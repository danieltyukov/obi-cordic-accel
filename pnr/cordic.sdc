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

# Setup uncertainty only. Applying the same allowance to hold made post-CTS hold
# repair unsatisfiable: OpenROAD hit its buffer ceiling ([RSZ-0060] Max buffer count
# reached) trying to pad every short path by 5 percent of the period. Hold gets a
# small fixed allowance instead, which is what it actually needs.
set_clock_uncertainty -setup [expr {$clk_period * 0.05}] clk
set_clock_uncertainty -hold  0.050 clk

# The accelerator is a subordinate on Croc's OBI crossbar. Both the request into it
# and the response out of it cross the interconnect, so allow a quarter period each
# way rather than pretending the ports are at the die edge.
set io_delay [expr {$clk_period * 0.25}]
# A minimum as well as a maximum, so the IO paths are not treated as arriving at time
# zero, which would make every one of them a hold violation to be buffered away.
set io_delay_min [expr {$clk_period * 0.05}]

set all_in  [all_inputs]
set data_in [list]
foreach p $all_in {
  if {[get_full_name $p] ne [get_full_name [lindex $clk_port 0]]} {
    lappend data_in $p
  }
}

set_input_delay  -max $io_delay     -clock clk $data_in
set_input_delay  -min $io_delay_min -clock clk $data_in
set_output_delay -max $io_delay     -clock clk [all_outputs]
set_output_delay -min $io_delay_min -clock clk [all_outputs]

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
