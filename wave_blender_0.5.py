import numpy as np
import soundfile as sf
import scipy.fft
import resampy
import os
os.environ["MPLCONFIGDIR"] = os.path.expanduser("~/.config/matplotlib")
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import (
    filedialog,
    messagebox,
    StringVar,
    IntVar,
    Label,
    Button,
    OptionMenu,
    Entry,
    Text,
    Scrollbar,
    Checkbutton,
)
from tkinter import ttk
from tkinter.ttk import Style
from scipy.signal import butter, lfilter
import pyaudio
import logging
import threading

# Number of samples for final output
TARGET_LENGTH = 256

audio_device_info = None  # Add this near the top of your file

def debug_print(message):
    logging.debug(message)
    if log_visible.get():
        log_text.insert("end", message + "\n")
        log_text.see("end")


def bandlimit(wave, sr=256, cutoff=512, order=1):
    nyquist = 0.5 * sr
    if cutoff >= nyquist:
        cutoff = nyquist - 1
    norm_cutoff = cutoff / nyquist
    b, a = butter(order, norm_cutoff, btype="low", analog=False)
    return lfilter(b, a, wave)


def normalize(wave):
    max_val = np.max(np.abs(wave))
    if max_val == 0:
        return wave
    return wave / max_val


def load_wave(file_path):
    """Load the full wave file without trimming to match successful script behavior."""
    try:
        debug_print(f"Trying to load with SoundFile: {file_path}")
        data, sr = sf.read(file_path, always_2d=True)

        # Print shape information for debugging
        debug_print(f"Loaded data shape: {data.shape}, Sample rate: {sr}")

        # Use the first channel if stereo
        if data.shape[1] > 1:
            data = data[:, 0]
        else:
            data = data.flatten()

        # Do not trim here - load the full wave
        debug_print(
            f"Successfully loaded with SoundFile: {file_path}, Length: {len(data)}"
        )
        return data, sr
    except Exception as e:
        debug_print(f"Error loading file with SoundFile: {str(e)}")
        return None, None


def extract_single_cycle(wave, min_length=128, max_length=256):
    """
    Extract a single natural cycle from the wave, between two consecutive zero-crossings,
    with no padding or trimming.
    """
    zero_crossings = np.where(np.diff(np.sign(wave)) != 0)[0]
    if len(zero_crossings) < 2:
        raise ValueError("Not enough zero-crossings to extract a cycle.")

    best_cycle = None
    best_dist = None

    for i in range(len(zero_crossings) - 1):
        start = zero_crossings[i]
        end = zero_crossings[i + 1]
        dist = end - start
        if min_length <= dist <= max_length:
            # Pick the first valid cycle found, or you can pick the one closest to 256
            if best_dist is None or abs(dist - 256) < abs(best_dist - 256):
                best_dist = dist
                best_cycle = (start, end)

    if best_cycle is None:
        raise ValueError("No suitable cycle found.")

    start, end = best_cycle
    cycle = wave[start:end]
    return cycle


def find_zero_crossing(signal):
    zero_crossings = np.where(np.diff(np.sign(signal)) != 0)[0]
    debug_print(
        f"Found zero-crossings at: {zero_crossings[:10]}..."
    )  # Print the first few zero-crossings
    return zero_crossings


def trim_to_zero_crossings(wave, threshold=0.01):
    """
    Trim leading silence, then start at the first zero-crossing after silence.
    Do NOT trim at the last zero-crossing; keep the rest of the wave.
    """
    abs_wave = np.abs(wave)
    above_thresh = np.where(abs_wave > threshold)[0]
    if above_thresh.size == 0:
        return wave  # All silence

    # Trim leading silence
    start = above_thresh[0]
    trimmed = wave[start:]

    # Find first zero-crossing in the trimmed wave
    zero_crossings = np.where(np.diff(np.sign(trimmed)) != 0)[0]
    if zero_crossings.size > 0:
        # Start at the first zero-crossing
        trimmed = trimmed[zero_crossings[0]:]

    return trimmed


def extract_clean_window(wave, fs, window_size=256, cutoff=1000):
    """
    Extract a clean, smooth wave window using adaptive amplitude detection.
    Uses a sliding window with peak detection.
    """
    debug_print(f"Extracting clean window from wave of length {len(wave)}")

    # Calculate a moving average of amplitudes to find quiet segments
    window_step = window_size // 4  # Slide by quarter windows
    min_avg_amp = float("inf")
    best_window = None

    # Sliding window search across the entire waveform
    for start in range(0, len(wave) - window_size, window_step):
        end = start + window_size
        chunk = wave[start:end]
        if len(chunk) < window_size:
            continue

        # Calculate the root mean square (RMS) amplitude for the current chunk
        rms_amp = np.sqrt(np.mean(chunk**2))
        max_amp = np.max(np.abs(chunk))

        debug_print(
            f"Window {start}-{end}: RMS amplitude = {rms_amp}, Max amplitude = {max_amp}"
        )

        # Update the best window if the RMS amplitude is the lowest found
        if rms_amp < min_avg_amp and max_amp < 0.05:
            min_avg_amp = rms_amp
            best_window = chunk
            debug_print(
                f"New best window found from {start} to {end}, RMS amplitude = {rms_amp}"
            )

    if best_window is not None:
        # Apply a Hann window to smooth the best chunk
        windowed = best_window * np.hanning(window_size)
        debug_print(f"Selected clean window with RMS amplitude: {min_avg_amp}")
        return windowed

    raise ValueError("Couldn't find a clean 256-sample window.")


def spectral_morph(waves):
    """Spectral morphing of multiple waveforms using magnitude and phase interpolation."""
    fft_waves = [
        scipy.fft.fft(wave, n=TARGET_LENGTH) for wave in waves
    ]  # Enforce target length in FFT

    magnitudes = [np.abs(fft_wave) for fft_wave in fft_waves]
    phases = [np.angle(fft_wave) for fft_wave in fft_waves]

    avg_magnitude = np.mean(magnitudes, axis=0)
    avg_phase = np.angle(np.sum(np.exp(1j * np.array(phases)), axis=0))

    combined_spectrum = avg_magnitude * np.exp(1j * avg_phase)
    morphed_wave = np.real(scipy.fft.ifft(combined_spectrum))

    # Trim or pad to ensure length
    if len(morphed_wave) < TARGET_LENGTH:
        morphed_wave = np.pad(
            morphed_wave, (0, TARGET_LENGTH - len(morphed_wave)), "constant"
        )
    elif len(morphed_wave) > TARGET_LENGTH:
        morphed_wave = morphed_wave[:TARGET_LENGTH]

    morphed_wave = normalize(morphed_wave)
    return morphed_wave


def weighted_blend(waves):
    """
    Weighted blending: combines waves by giving more weight to louder signals.
    """
    # Calculate RMS for each wave to determine the weights
    rms_values = [np.sqrt(np.mean(np.square(wave))) for wave in waves]
    total_rms = sum(rms_values)

    # Avoid division by zero and assign equal weights if total RMS is zero
    if total_rms == 0:
        weights = [1 / len(waves) for _ in waves]
    else:
        weights = [rms / total_rms for rms in rms_values]

    # Initialize the blended wave with zeros of TARGET_LENGTH
    blended_wave = np.zeros(TARGET_LENGTH)

    for wave, weight in zip(waves, weights):
        # Ensure each wave is of the correct length by trimming or padding
        if len(wave) < TARGET_LENGTH:
            # Instead of padding with zeros, repeat the wave to fill the length
            repeats = TARGET_LENGTH // len(wave) + 1
            wave = np.tile(wave, repeats)[:TARGET_LENGTH]
        elif len(wave) > TARGET_LENGTH:
            wave = wave[:TARGET_LENGTH]

        # Blend using the calculated weight
        blended_wave += wave * weight

    # Normalize the final blended wave to maintain volume consistency
    blended_wave = normalize(blended_wave)

    # Check and fix the final length in case of rounding errors
    if len(blended_wave) < TARGET_LENGTH:
        blended_wave = np.pad(
            blended_wave, (0, TARGET_LENGTH - len(blended_wave)), "constant"
        )
    elif len(blended_wave) > TARGET_LENGTH:
        blended_wave = blended_wave[:TARGET_LENGTH]

    return blended_wave


def resample_wave(wave, sr_in, sr_out):
    return resampy.resample(wave, sr_in, sr_out), sr_out


def plot_waveform(wave, title="Waveform Preview"):
    plt.figure(figsize=(8, 3))
    plt.plot(wave, color="dodgerblue")
    plt.title(title)
    plt.xlabel("Samples")
    plt.ylabel("Amplitude")
    plt.grid(True)
    plt.tight_layout()
    plt.show()


def extract_clean_cycle(signal, fs, window_size=256, cutoff=1000):
    """
    Extract clean 256-sample chunk from the wave.
    Applies low-pass filtering and finds a clean window.
    """

    def find_zero_crossing(signal):
        zero_crossings = np.where(np.diff(np.sign(signal)) != 0)[0]
        return zero_crossings

    midpoint = len(signal) // 2
    search_range = signal[
        max(midpoint - window_size, 0) : min(midpoint + window_size, len(signal))
    ]
    zc = find_zero_crossing(search_range)

    for i in range(len(zc) - 1):
        start = zc[i]
        end = start + window_size
        if end < len(search_range):
            chunk = search_range[start:end]
            if len(chunk) == window_size:
                # Apply a Hann window to smooth edges
                windowed = chunk * np.hanning(window_size)
                return (
                    windowed,
                    start + midpoint - window_size // 2,
                    end + midpoint - window_size // 2,
                )

    raise ValueError("Couldn't find a clean 256-sample window.")


def select_files():
    global file_paths
    file_paths = filedialog.askopenfilenames(filetypes=[("WAV files", "*.wav")])
    file_paths = [os.path.abspath(path) for path in file_paths]
    if file_paths:
        file_table.config(state="normal")
        file_table.delete(1.0, "end")
        for path in file_paths:
            file_table.insert("end", f"{os.path.basename(path)}\n")

        file_table.config(state="disabled")
        debug_print(f"Selected files: {file_paths}")


def save_output():
    path = filedialog.asksaveasfilename(
        defaultextension=".ws6", filetypes=[("WS6 audio", "*.ws6")]
    )
    if path:
        output_file.set(path)
        debug_print(f"Output file set to: {path}")


def toggle_log():
    if log_visible.get():
        log_frame.pack(fill="x", pady=5)
    else:
        log_frame.pack_forget()

def process_files(file_paths, blend_method, resample_rate, clean_mode, output_path):
    """Process the selected wave files and generate the output."""

    num_files = len(file_paths)

    # Enforce correct file count for each mode
    if blend_method == 2 and num_files != 1:
        messagebox.showerror(
            "Error",
            "Single Wave (No Blending) mode requires exactly 1 file.\n"
            "Please select only one file for this mode."
        )
        debug_print(f"Single Wave mode selected with {num_files} files.")
        return
    elif blend_method in [0, 1] and num_files not in [2, 4, 8]:
        messagebox.showerror(
            "Error",
            "Spectral Morphing and Weighted Blending require 2, 4, or 8 files.\n"
            "Please select the correct number of files for this mode."
        )
        debug_print(f"Blending mode {blend_method} selected with {num_files} files.")
        return
    
    debug_print(f"Starting file processing with {len(file_paths)} files")
    waves = []

    for path in file_paths:
        debug_print(f"Attempting to process file: {path}")
        wave, sr = load_wave(path)
        if wave is None or sr is None:
            debug_print(f"Skipping invalid file: {path}")
            continue

        # Remove DC offset first
        wave = wave - np.mean(wave)

        # --- Apply bandlimit filter before any further processing ---
        wave = bandlimit(wave, sr=sr, cutoff=512, order=1)
        debug_print(f"Applied bandlimit filter: cutoff=512Hz, order=1, sr={sr}")

        original_length = len(wave)
        wave = trim_to_zero_crossings(wave, threshold=0.01)
        trimmed_length = len(wave)
        samples_trimmed = original_length - trimmed_length
        debug_print(f"Trimmed {samples_trimmed} samples of start silence (from {original_length} to {trimmed_length})")
        debug_print(f"Trimmed silence: first 10 samples {wave[:10]}")
        debug_print(f"Last 10 samples after zero-crossing trim: {wave[-10:]}")

        # Skip the first 4000 samples after silence
        if len(wave) > 4000:
            wave = wave[4000:]
            debug_print("Skipped first 4000 samples after silence trim.")
        else:
            debug_print("Wave too short to skip 4000 samples after silence trim.")

        # Extract the single cycle
        if blend_method == 2:  # Single Wave mode
            try:
                debug_print(f"Finding first zero crossing after skip for: {path}")
                zero_crossings = np.where(np.diff(np.sign(wave)) != 0)[0]
                if zero_crossings.size == 0 or zero_crossings[0] + 256 > len(wave):
                    debug_print(f"Not enough data after first zero crossing for {path}")
                    continue
                start = zero_crossings[0]
                wave = wave[start : start + 256]
                debug_print(f"Selected 256 samples from first zero crossing: {start} to {start+256}")
            except Exception as e:
                debug_print(f"Error extracting 256 samples from {path}: {str(e)}")
                continue
        elif clean_mode:
            debug_print(f"Finding clean window at original sample rate: {sr} Hz")
            wave = extract_clean_window(wave, sr, TARGET_LENGTH)
            debug_print(f"Extracted clean window from: {path}")

        # Step 2: Resample after extracting the clean window
        if resample_rate and sr != resample_rate:
            try:
                debug_print(
                    f"Resampling extracted window from {sr} to {resample_rate} Hz for file: {path}"
                )
                wave, _ = resample_wave(wave, sr, resample_rate)
                sr = resample_rate
                debug_print(f"Resampled clean window length: {len(wave)}")
            except Exception as e:
                messagebox.showerror(
                    "Error", f"Resampling failed for {path}\nReason: {str(e)}"
                )
                debug_print(f"Resampling error for {path}: {str(e)}")
                continue

        # Trim to 256 if necessary
        if len(wave) > TARGET_LENGTH:
            wave = wave[:TARGET_LENGTH]
            debug_print(f"Trimmed wave to target length: {TARGET_LENGTH}")

        waves.append(wave)

    if not waves:
        messagebox.showerror("Error", "No valid wave files loaded for processing.")
        debug_print("No valid wave files loaded for processing.")
        return

    try:
        # Check number of files
        num_files = len(waves)

        # Ensure valid file count (1, 2, 4, 8)
        if num_files not in [1, 2, 4, 8]:
            messagebox.showerror("Error", "Please select 1, 2, 4, or 8 files only.")
            debug_print(f"Invalid number of files selected: {num_files}")
            return

        debug_print(f"Number of files: {num_files}")

        # --- Blending method selection ---
        if blend_method == 2:
            debug_print("Blending method: Single Wave (No Blending)")
            blended_wave = waves[0]  # Just use the first wave
        elif blend_method == 1:
            debug_print("Blending method: Spectral Morphing (FFT)")
            blended_wave = spectral_morph(waves)
        else:
            debug_print("Blending method: Weighted Blending")
            blended_wave = weighted_blend(waves)

        # Check the resulting wave length after blending
        debug_print(f"Blended wave length before trimming/padding: {len(blended_wave)}")


        # Final adjustment of length if necessary
        if len(blended_wave) != TARGET_LENGTH:
            if len(blended_wave) < TARGET_LENGTH:
                blended_wave = np.pad(
                    blended_wave, (0, TARGET_LENGTH - len(blended_wave)), "constant"
                )
                debug_print(
                    f"Padded blended wave to target length: {len(blended_wave)}"
                )
            else:
                blended_wave = blended_wave[:TARGET_LENGTH]
                debug_print(
                    f"Trimmed blended wave to target length: {len(blended_wave)}"
                )

        # Check for zero or near-zero values indicating blending issues
        if np.allclose(blended_wave, 0):
            debug_print("Warning: Blended wave consists mostly of zero values.")

        # Normalize the final blended wave
        blended_wave = normalize(blended_wave)
        debug_print(f"Final blended wave length: {len(blended_wave)}")

        # Final padding to ensure exact length
        if len(blended_wave) < TARGET_LENGTH:
            blended_wave = np.pad(
                blended_wave, (0, TARGET_LENGTH - len(blended_wave)), "constant"
            )
        elif len(blended_wave) > TARGET_LENGTH:
            blended_wave = blended_wave[:TARGET_LENGTH]

        # signed 16 bit is -32768 to 32767
        result_int16 = np.int16(blended_wave * 32767)

        # Plot exactly what is being written to the file
        plot_waveform(result_int16 / 32767.0, "Final Output")

        result_int16.tofile(output_path)

        debug_print(
            f"✅ Blended wave saved to: {output_path}, Length: {len(blended_wave)}"
        )
        enable_audition()

    except Exception as e:
        messagebox.showerror("Error", f"Failed to blend waves\nReason: {str(e)}")
        debug_print(f"Error during wave blending: {str(e)}")


def start_processing():
    try:
        debug_print("Start Processing button clicked")

        # Check if files have been selected
        if not file_paths:
            messagebox.showerror("Error", "No files selected.")
            debug_print("Error: No files selected at start processing.")
            return

        # Get the number of selected files
        num_files = len(file_paths)
        debug_print(f"Number of selected files: {num_files}")

        # Log the processing settings
        blend_map = {
            2: "Single Wave (No Blending)",
            1: "Spectral Morphing (FFT)",
            0: "Weighted Blending",
        }
        debug_print(f"Blending method: {blend_map.get(blend_method.get(), 'Unknown')}")
        debug_print(f"Resample rate: {resample_rate.get()}")
        debug_print(f"Clean mode: {'Enabled' if clean_mode.get() else 'Disabled'}")
        debug_print(f"Output path: {output_file.get()}")

        # Check if output path is provided
        if not output_file.get():
            messagebox.showerror("Error", "Please specify an output file.")
            debug_print("Error: No output file specified.")
            return

        # Start processing the selected files
        debug_print("Starting file processing...")
        process_files(
            file_paths,
            blend_method.get(),
            int(resample_rate.get()),
            clean_mode.get(),
            output_file.get(),
        )
        debug_print("File processing completed.")
    except Exception as e:
        messagebox.showerror("Error", f"Start processing failed: {str(e)}")
        debug_print(f"Error in start_processing: {str(e)}")


def query_audio_devices():
    global audio_device_info
    if audio_device_info is not None:
        return audio_device_info  # Already queried
    p = pyaudio.PyAudio()
    info = p.get_default_output_device_info()
    preferred_rate = int(info["defaultSampleRate"])
    max_channels = info["maxOutputChannels"]
    print(f"Default output device: {info['name']}")
    print(f"Preferred sample rate: {preferred_rate}")
    print(f"Max output channels: {max_channels}")
    p.terminate()
    audio_device_info = info
    return info


def resample_audio(data, original_rate, target_rate):
    if original_rate != target_rate:
        print(f"Resampling from {original_rate} to {target_rate} Hz")
        resampled = resampy.resample(
            data.astype(np.float32), original_rate, target_rate
        )
        return np.clip(resampled, -32768, 32767).astype(np.int16)
    return data


def play_pcm_to_all_outputs(file_path, original_rate=44100, unsigned=False):
    info = query_audio_devices()  # Will only query once
    rate = int(info["defaultSampleRate"])
    channels = info["maxOutputChannels"]
    p = pyaudio.PyAudio()

    # Read file as unsigned 16-bit or signed 16-bit depending on file format
    if unsigned:
        data = np.fromfile(file_path, dtype=np.uint16)
        data = data.astype(np.int32) - 32768
        data = data.astype(np.int16)
    else:
        data = np.fromfile(file_path, dtype=np.int16)

    # For now, just repeat the data if it's short for a clear test
    if len(data) < rate * 2:
        data = np.tile(data, int((rate * 2) / len(data)) + 1)
    frame_count = len(data)
    # Build all-channel buffer: same audio in every channel
    out = np.tile(data[:frame_count], (channels, 1)).T.astype(np.int16)
    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            output=True,
            output_device_index=info["index"],
        )
        stream.write(out.tobytes())
        stream.stop_stream()
        stream.close()
    except Exception as e:
        print(f"Playback failed: {e}")
    p.terminate()


def enable_audition():
    audition_button.config(state="normal")


def start_preview():
    try:
        original_rate = int(resample_rate.get())
        filepath = output_file.get()
        # Call with (filepath, original file sample rate, stereo pair to use)
        threading.Thread(
            target=play_pcm_to_all_outputs,
            args=(
                output_file.get(),
                int(resample_rate.get()),
            ),  # Only file path and rate!
            daemon=True,
        ).start()
    except ValueError:
        print("Error: Invalid sample rate. Please ensure it is a number.")


def stop_preview():
    pyaudio.PyAudio().terminate()
    print("Audio stopped.")


root = tk.Tk()
root.title("Wave Blender v0.5")
root.geometry("600x600")

style = Style()
style.configure("TButton", font=("Arial", 10), padding=5)
style.configure("TLabel", font=("Arial", 10))
style.configure("TFrame", background="#FFFFFF")

loop_audio = IntVar(value=1)

container = ttk.Frame(root, padding=10)
container.pack(fill="both", expand=True)

file_frame = ttk.Frame(container)
file_frame.pack(pady=5, fill="both", expand=True)  # Allow file_frame to expand

Label(file_frame, text="1. Select WAV files (1, 2, 4, 8):", anchor="w").pack(
    side="top", anchor="w"
)
Button(file_frame, text="Select Files", command=select_files).pack(
    side="top", padx=10, anchor="w"
)

# Add a frame for file_table and its scrollbar
file_table_frame = ttk.Frame(file_frame)
file_table_frame.pack(fill="both", expand=True)

file_table = Text(file_table_frame, height=5, width=50, state="disabled", wrap="none")
file_table.pack(side="left", fill="both", expand=True)

file_scrollbar = Scrollbar(file_table_frame, command=file_table.yview)
file_table.config(yscrollcommand=file_scrollbar.set)
file_scrollbar.pack(side="right", fill="y")

blend_frame = ttk.Frame(container)
blend_frame.pack(pady=5, fill="x")
Label(blend_frame, text="2. Choose Blending Method:").pack(anchor="w")
blend_method = IntVar(value=2)
tk.Radiobutton(
    blend_frame,
    text="Single Wave (No Blending)",
    variable=blend_method,
    value=2,
).pack(anchor="w")
tk.Radiobutton(
    blend_frame,
    text="Spectral Morphing (FFT)",
    variable=blend_method,
    value=1,
).pack(anchor="w")
tk.Radiobutton(
    blend_frame, text="Weighted Blending", variable=blend_method, value=0
).pack(anchor="w")

resample_frame = ttk.Frame(container)
resample_frame.pack(pady=5, fill="x")
Label(resample_frame, text="3. Select Resampling Rate:", anchor="w").pack(side="left")
resample_rate = StringVar(value="44100")
options = ["192000", "96000", "48000", "44100"]
OptionMenu(resample_frame, resample_rate, *options).pack(side="left", padx=10)

clean_mode = IntVar(value=0)  # Set to 0 to disable by default
tk.Checkbutton(
    container, text="Extract Clean 256-Sample Window", variable=clean_mode
).pack(anchor="w", pady=5)

log_visible = IntVar(value=0)
tk.Checkbutton(
    container, text="Show Log Window", variable=log_visible
).pack(anchor="w", pady=5)

output_frame = ttk.Frame(container)
output_frame.pack(pady=5, fill="x")
Label(output_frame, text="4. Choose Output File:", anchor="w").pack(side="left")
output_file = StringVar()
Button(output_frame, text="Select Output File", command=save_output).pack(
    side="left", padx=10
)

Button(container, text="Start Processing", command=start_processing).pack(pady=5)

audition_frame = ttk.Frame(container)
audition_frame.pack(pady=5, fill="x")
audition_button = Button(
    audition_frame, text="Audition Wave", command=start_preview, state="disabled"
)
audition_button.pack(side="left", padx=5)
stop_button = Button(audition_frame, text="Stop Preview", command=stop_preview)
stop_button.pack(side="left", padx=5)
# Checkbutton(audition_frame, text="Loop", variable=loop_audio).pack(side="left", padx=5)

log_frame = ttk.Frame(container)
log_frame.pack(fill="both", expand=True, pady=5)  # Allow log_frame to expand

log_text = Text(log_frame, height=8, wrap="word")
log_text.pack(side="left", fill="both", expand=True)  # Allow log_text to expand

scrollbar = Scrollbar(log_frame, command=log_text.yview)
log_text.config(yscrollcommand=scrollbar.set)
scrollbar.pack(side="right", fill="y")

root.mainloop()
