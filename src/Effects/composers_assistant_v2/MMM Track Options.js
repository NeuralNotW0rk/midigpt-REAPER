desc:MMM Track-Specific Generation Options

slider1:jsfx_id=349583025<349583025, 349583025, 1>-jsfx_id

// Track-specific temperature override
slider10:track_temperature=-1<-1, 2.0, 0.1>Track Temperature (-1 = use global)

// Polyphony controls
slider20:vert_density=-1<-1, 4, 1{-1 = No preference,0 = Mono,1 = 1.01-2 notes,2 = 2.01-3 notes,3 = 3.01-4 notes,4 = More than 4 notes}>Vertical note density (average)
slider21:n_pitch_classes=-1<-1, 4, 1{-1 = No preference,0 = 1 pitch class,1 = 1.01-2 pitch classes,2 = 2.01-3 pitch classes,3 = 3.01-4 pitch classes,4 = More than 4 pitch classes}>Number of pitch classes per onset (average)

// Rhythm controls
slider30:horiz_density=4<-1, 5, 1{-1 = No preference,0 = Less than half notes,1 = Half notes to quarter notes,2 = Quarter notes to 8th notes,3 = 8th notes to 16th notes,4 = 16th notes to 4.5 onsets per QN,5 = 4.5+ onsets per QN}>Horizontal note onset density (average)
slider31:rhy_ins=3<-1, 3, 1{-1 = No preference,0 = None/Low,1 = Medium,2 = High}>Rhythmic interest

// Pitch movement
slider40:step_bin=4<-1,6,1{-1 = No preference,0 = 0%,1 = 1-20%,2 = 20-40%,3 = 40-60%,4 = 60-80%,5 = 80-99%,6 = 100%}>Step propensity
slider41:leap_bin=3<-1,6,1{-1 = No preference,0 = 0%,1 = 1-20%,2 = 20-40%,3 = 40-60%,4 = 60-80%,5 = 80-99%,6 = 100%}>Leap propensity

// Pitch range controls (strict and loose are mutually exclusive)
slider50:low_note_strict=-1<-1,127,1>Lowest pitch (strict)
slider51:high_note_strict=-1<-1,127,1>Highest pitch (strict)
slider52:low_note_loose=-1<-1,127,1>Lowest pitch (loose)
slider53:high_note_loose=-1<-1,127,1>Highest pitch (loose)

// Internal parameter for compatibility
slider100:rpr_script_min_val=0<0, 0, 1>-rpr_script_min_val

in_pin:none
out_pin:none

@init
// Store previous values for change detection
hns_prev = high_note_strict;
hnl_prev = high_note_loose;
lns_prev = low_note_strict;
lnl_prev = low_note_loose;
step_prev = step_bin;
leap_prev = leap_bin;
track_temp_prev = track_temperature;

@slider
// Handle strict/loose pitch range mutual exclusion
hns_prev != high_note_strict ? (
  high_note_strict > -1 ? (
    high_note_loose = -1;
  );
);

hnl_prev != high_note_loose ? (
  high_note_loose > -1 ? (
    high_note_strict = -1;
  );
);

lns_prev != low_note_strict ? (
  low_note_strict > -1 ? (
    low_note_loose = -1;
  );
);

lnl_prev != low_note_loose ? (
  low_note_loose > -1 ? (
    low_note_strict = -1;
  );
);

// Handle step/leap relationship (must sum to at most 9, excluding special case of 7)
step_prev != step_bin ? (
  step_bin + leap_bin > 9 ? (
    leap_bin = 9 - step_bin;
  );
  step_bin == 7 && leap_bin != 0 ? (
    leap_bin = 1;
  );
);

leap_prev != leap_bin ? (
  step_bin + leap_bin > 9 ? (
    step_bin = 9 - leap_bin;
  );
  leap_bin == 7 && step_bin != 0 ? (
    step_bin = 1;
  );
);

// Validate track temperature
track_temperature != -1 && track_temperature < 0.5 ? (
  track_temperature = 0.5;
);

track_temperature > 2.0 ? (
  track_temperature = 2.0;
);

// Store current values
hns_prev = high_note_strict;
hnl_prev = high_note_loose;
lns_prev = low_note_strict;
lnl_prev = low_note_loose;
step_prev = step_bin;
leap_prev = leap_bin;
track_temp_prev = track_temperature;
