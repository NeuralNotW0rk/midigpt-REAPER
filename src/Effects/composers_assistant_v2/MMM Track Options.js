desc:MMM Track-Specific Generation Options

slider1:jsfx_id=349583025<349583025, 349583025, 1>-jsfx_id

// Track-specific MidiGPT parameters
slider10:track_temperature=-1<-1, 2.0, 0.1>Track Temperature (-1 = use global)
slider11:track_density=-1<-1, 4, 1{-1 = No preference,0 = Sparse,1 = Low,2 = Medium,3 = Dense,4 = Very Dense}>Track Density
slider12:track_style=-1<-1, 4, 1{-1 = No preference,0 = Melodic,1 = Harmonic,2 = Rhythmic,3 = Bass,4 = Percussion}>Track Style

// Polyphony controls (same as CA for compatibility)
slider20:vert_density=-1<-1, 4, 1{-1 = No preference,0 = Mono,1 = 1.01-2 notes,2 = 2.01-3 notes,3 = 3.01-4 notes,4 = More than 4 notes}>Vertical note density (average)
slider21:n_pitch_classes=-1<-1, 4, 1{-1 = No preference,0 = 1 pitch class,1 = 1.01-2 pitch classes,2 = 2.01-3 pitch classes,3 = 3.01-4 pitch classes,4 = More than 4 pitch classes}>Number of pitch classes per onset (average)

// Rhythm controls (same as CA for compatibility)
slider30:horiz_density=4<-1, 5, 1{-1 = No preference,0 = Less than half notes,1 = Half notes to quarter notes,2 = Quarter notes to 8th notes,3 = 8th notes to 16th notes,4 = 16th notes to 4.5 onsets per QN,5 = 4.5+ onsets per QN}>Horizontal note onset density (average)
slider31:rhy_ins=3<-1, 3, 1{-1 = No preference,0 = None/Low,1 = Medium,2 = High}>Rhythmic interest

// Pitch movement (same as CA for compatibility)
slider40:step_bin=4<-1,6,1{-1 = No preference,0 = 0%,1 = 1-20%,2 = 20-40%,3 = 40-60%,4 = 60-80%,5 = 80-99%,6 = 100%}>Step propensity
slider41:leap_bin=3<-1,6,1{-1 = No preference,0 = 0%,1 = 1-20%,2 = 20-40%,3 = 40-60%,4 = 60-80%,5 = 80-99%,6 = 100%}>Leap propensity

// Pitch range controls (same as CA for compatibility)
slider50:low_note_strict=-1<-1,127,1>Lowest pitch (strict)
slider51:high_note_strict=-1<-1,127,1>Highest pitch (strict)
slider52:low_note_loose=-1<-1,127,1>Lowest pitch (loose)
slider53:high_note_loose=-1<-1,127,1>Highest pitch (loose)

// Velocity controls (same as CA for compatibility)
slider60:low_vel=-1<-1, 127, 1>Lowest velocity for new notes
slider61:high_vel=-1<-1, 127, 1>Highest velocity for new notes

// Additional options
slider70:octave_shift_allowed=1<0, 1, 1{No,Yes}>New measures can be vertical copies of others
slider71:instrument_hint=-1<-1, 127, 1>Instrument Hint (-1 = auto)

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
// Handle strict/loose pitch range mutual exclusion (same logic as CA)
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

// Handle step/leap relationship (same as CA)
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
track_temperature != -1 && track_temperature <= 0 ? (
  track_temperature = 0.1;
);

// Store current values
hns_prev = high_note_strict;
hnl_prev = high_note_loose;
lns_prev = low_note_strict;
lnl_prev = low_note_loose;
step_prev = step_bin;
leap_prev = leap_bin;
track_temp_prev = track_temperature;
