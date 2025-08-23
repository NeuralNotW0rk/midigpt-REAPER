desc:midigpt Global Options

slider1:jsfx_id=54964318<54964318, 54964318, 1>-jsfx_id

// Core midigpt generation parameters
slider10:temperature=1.0<0.1, 2.0, 0.1>Temperature
slider11:tracks_per_step=1<1, 8, 1>Tracks per Step
slider12:bars_per_step=1<1, 4, 1>Bars per Step
slider13:model_dim=4<2, 8, 1>Model Dimension (Context Window)
slider14:percentage=100<10, 100, 5>Generation Percentage
slider15:max_steps=200<50, 1000, 10>Max Steps

// Sampling and generation control
slider20:batch_size=1<1, 4, 1>Batch Size
slider21:shuffle=1<0, 1, 1{No,Yes}>Shuffle Steps
slider22:sampling_seed=-1<-1, 9999, 1>Sampling Seed (-1 = random)
slider23:mask_top_k=0<0, 50, 1>Mask Top K (0 = disabled)
slider24:polyphony_hard_limit=6<1, 16, 1>Polyphony Hard Limit

// Original options to maintain compatibility
slider30:disp_tr_to_midi_inst=1<0, 1, 1{No,Yes}>Display Track-to-MIDI Instrument
slider31:gen_notes_selected=1<0, 1, 1{No,Yes}>Generated Notes are Selected
slider32:display_warnings=1<0, 1, 1{No,Yes}>Display Warnings
slider33:verbose=0<0, 1, 1{No,Yes}>Verbose Output

in_pin:none
out_pin:none

@init
// Store previous values for change detection
temp_prev = temperature;
tps_prev = tracks_per_step;
bps_prev = bars_per_step;
md_prev = model_dim;
pct_prev = percentage;
ms_prev = max_steps;

@slider
// Validate parameter relationships and constraints

// Ensure model_dim >= bars_per_step
model_dim < bars_per_step ? (
  model_dim = bars_per_step;
);

// Ensure reasonable relationships
bars_per_step > model_dim ? (
  bars_per_step = model_dim;
);

// Temperature must be positive for sampling
temperature <= 0 ? (
  temperature = 0.1;
);

// Store current values
temp_prev = temperature;
tps_prev = tracks_per_step;
bps_prev = bars_per_step;
md_prev = model_dim;
pct_prev = percentage;
ms_prev = max_steps;