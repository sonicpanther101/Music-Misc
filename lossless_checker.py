#!/usr/bin/env python3
"""
lossless_checker.py - Batch scanner that flags FLAC/WAV/AIFF files that were
likely transcoded from a lossy source (e.g. MP3 -> FLAC).

How it works:
  For each file, several ~8s windows are sampled across the track (not the
  whole file, to keep things fast) and averaged into a single power spectrum.
  We then look at the high-frequency region for:
    1. Where energy content effectively stops (the "cutoff" frequency).
    2. How STEEP that dropoff is (dB lost per kHz).

  A genuine lossless recording either has energy content out to Nyquist, or a
  GRADUAL natural rolloff (typical of older masters, vinyl rips, etc).
  A lossy-encoded source has a hard low-pass "shelf" - a fast, steep dropoff
  at a fairly specific frequency (which roughly tells you the source bitrate).

  This is a heuristic, same family as auCDtect / Lossless Audio Checker /
  Spek-by-eye. It will not be 100% perfect (near-transparent very-high-bitrate
  lossy encodes, or unusual masters, can fool it) - use it to triage a big
  library down to a shortlist you spot check, not as absolute proof.

Usage:
  pip install numpy scipy soundfile --break-system-packages
  python3 lossless_checker.py /path/to/music --recursive --csv report.csv

Requires: numpy, scipy, soundfile (soundfile needs libsndfile, which reads
FLAC/WAV/AIFF natively - no ffmpeg needed for those formats).
"""

import argparse
import concurrent.futures as cf
import csv
import os
import sys

import numpy as np
import soundfile as sf
from scipy.signal import stft

LOSSLESS_EXTS = {".flac", ".wav", ".aif", ".aiff", ".alac", ".ape", ".wv"}

# Rough map of cutoff frequency -> likely lossy source, for CD-quality (44.1/48kHz) audio
BITRATE_HINTS = [
    (20800, "320kbps (or near-transparent) MP3/lossy"),
    (19500, "256/224kbps MP3/AAC"),
    (18500, "192kbps MP3"),
    (17000, "160kbps MP3"),
    (15500, "128kbps MP3"),
    (0,     "very low bitrate (<128kbps) or heavily filtered source"),
]


def bitrate_hint(cutoff_hz):
    for threshold, label in BITRATE_HINTS:
        if cutoff_hz >= threshold:
            return label
    return "unknown"


def analyze_file(path, n_windows=6, window_sec=8.0):
    """Thin wrapper: guarantees we always return a result dict, never raise,
    even on totally unexpected errors - so one bad file can't kill the batch."""
    try:
        return _analyze_file_inner(path, n_windows=n_windows, window_sec=window_sec)
    except Exception as e:
        return {"path": path, "verdict": "ERROR", "detail": f"unexpected error: {e}"}


def _analyze_file_inner(path, n_windows=6, window_sec=8.0):
    try:
        info = sf.info(path)
    except Exception as e:
        return {"path": path, "verdict": "ERROR", "detail": f"could not read: {e}"}

    sr = info.samplerate
    nyquist = sr / 2
    duration = info.frames / sr
    if duration < 5:
        return {"path": path, "verdict": "SKIP", "detail": "too short to analyze"}

    win_len = int(window_sec * sr)
    n_windows = max(1, min(n_windows, int(duration // window_sec)))
    starts = np.linspace(0, max(0, info.frames - win_len), n_windows, dtype=int)

    spectra = []
    try:
        with sf.SoundFile(path) as f:
            for start in starts:
                try:
                    f.seek(int(start))
                    block = f.read(win_len, dtype="float32", always_2d=True)
                except Exception:
                    # corrupt/truncated region - skip this window, keep going
                    continue
                if block.shape[0] < win_len // 2:
                    continue
                mono = block.mean(axis=1)
                freqs, _, Zxx = stft(mono, fs=sr, nperseg=8192, noverlap=4096)
                power_db = 20 * np.log10(np.abs(Zxx).mean(axis=1) + 1e-10)
                spectra.append(power_db)
    except Exception as e:
        return {"path": path, "verdict": "ERROR", "detail": f"decode error: {e}"}

    if not spectra:
        return {"path": path, "verdict": "ERROR", "detail": "no usable audio windows (possibly corrupt file)"}

    avg_db = np.mean(spectra, axis=0)
    avg_db -= avg_db.max()  # normalize to 0dB peak

    # noise floor = median level in the top 3% of the spectrum (near Nyquist)
    top_band = avg_db[freqs > nyquist * 0.97]
    noise_floor = np.median(top_band) if len(top_band) else avg_db[-1]

    # scan downward from Nyquist to find where content rises clearly above noise floor
    threshold = noise_floor + 12  # dB above floor counts as "real content"
    cutoff_idx = None
    for i in range(len(freqs) - 1, -1, -1):
        if avg_db[i] > threshold:
            cutoff_idx = i
            break
    # if no point exceeded threshold, content is flat/strong all the way to Nyquist
    cutoff_hz = nyquist if cutoff_idx is None else freqs[cutoff_idx]

    # steepness: dB drop per kHz across a 1.5kHz window straddling the cutoff
    lo = max(cutoff_hz - 750, freqs[0])
    hi = min(cutoff_hz + 750, freqs[-1])
    lo_val = np.interp(lo, freqs, avg_db)
    hi_val = np.interp(hi, freqs, avg_db)
    span_khz = (hi - lo) / 1000.0
    slope_db_per_khz = (lo_val - hi_val) / span_khz if span_khz > 0 else 0

    ratio = cutoff_hz / nyquist if nyquist else 0
    steep = slope_db_per_khz > 12  # tune this if you get false positives on your library

    if ratio > 0.96:
        verdict = "CLEAN"
        detail = f"content extends to {cutoff_hz:.0f}Hz (Nyquist {nyquist:.0f}Hz) - looks genuine"
    elif steep:
        verdict = "SUSPECT"
        detail = (f"hard cutoff at ~{cutoff_hz:.0f}Hz, steep {slope_db_per_khz:.1f}dB/kHz "
                   f"-> likely transcoded from {bitrate_hint(cutoff_hz)}")
    else:
        verdict = "GRADUAL_ROLLOFF"
        detail = (f"rolloff at ~{cutoff_hz:.0f}Hz but gentle ({slope_db_per_khz:.1f}dB/kHz) "
                   f"- could be an old master/analog source, not necessarily transcoded")

    return {
        "path": path,
        "verdict": verdict,
        "detail": detail,
        "samplerate": sr,
        "cutoff_hz": round(cutoff_hz),
        "nyquist_hz": round(nyquist),
        "slope_db_per_khz": round(slope_db_per_khz, 1),
    }


def find_files(root, recursive):
    if recursive:
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                if os.path.splitext(name)[1].lower() in LOSSLESS_EXTS:
                    yield os.path.join(dirpath, name)
    else:
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if os.path.isfile(full) and os.path.splitext(name)[1].lower() in LOSSLESS_EXTS:
                yield full


def main():
    ap = argparse.ArgumentParser(description="Batch-detect fake/transcoded lossless audio files.")
    ap.add_argument("folder", help="Folder to scan")
    ap.add_argument("--recursive", action="store_true", help="Scan subfolders too")
    ap.add_argument("--csv", help="Write full results to this CSV path")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4, help="Parallel workers")
    ap.add_argument("--resume", action="store_true",
                     help="If --csv already exists, skip files already recorded in it and append new results")
    args = ap.parse_args()

    files = list(find_files(args.folder, args.recursive))
    if not files:
        print(f"No FLAC/WAV/AIFF files found in {args.folder}")
        sys.exit(0)

    fieldnames = ["path", "verdict", "detail", "samplerate", "cutoff_hz",
                  "nyquist_hz", "slope_db_per_khz"]

    already_done = set()
    write_header = True
    if args.csv and args.resume and os.path.exists(args.csv):
        with open(args.csv, newline="") as f:
            for row in csv.DictReader(f):
                already_done.add(row["path"])
        write_header = False
        print(f"Resuming: {len(already_done)} files already recorded in {args.csv}, skipping those.")

    todo = [p for p in files if p not in already_done]
    print(f"Scanning {len(todo)} files ({len(files) - len(todo)} already done) with {args.workers} workers...\n")

    if not todo:
        print("Nothing left to scan.")
        return

    csv_file = open(args.csv, "a", newline="") if args.csv else None
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore") if csv_file else None
    if writer and write_header:
        writer.writeheader()

    results = []
    try:
        with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(analyze_file, p): p for p in todo}
            for i, fut in enumerate(cf.as_completed(futures), 1):
                path = futures[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    # worker process itself died (e.g. segfault in a C decoder) - don't lose the file
                    res = {"path": path, "verdict": "ERROR", "detail": f"worker crashed: {e}"}
                results.append(res)
                print(f"[{i}/{len(todo)}] {res['verdict']:16s} {os.path.basename(res['path'])}")
                if writer:
                    writer.writerow(res)
                    csv_file.flush()
    finally:
        if csv_file:
            csv_file.close()

    suspects = [r for r in results if r["verdict"] == "SUSPECT"]
    gradual = [r for r in results if r["verdict"] == "GRADUAL_ROLLOFF"]
    errors = [r for r in results if r["verdict"] in ("ERROR", "SKIP")]

    print("\n" + "=" * 70)
    print(f"SUMMARY: {len(results)} files scanned this run")
    print(f"  Likely transcoded (SUSPECT): {len(suspects)}")
    print(f"  Gradual rolloff (probably fine, worth a quick listen): {len(gradual)}")
    print(f"  Errors/skipped: {len(errors)}")
    print("=" * 70)

    if suspects:
        print("\nSUSPECT FILES:")
        for r in suspects:
            print(f"  {r['path']}\n    -> {r['detail']}")

    if errors:
        print(f"\n{len(errors)} files had errors/were skipped - see the CSV for details" +
              (f" ({args.csv})" if args.csv else " (run with --csv to save them)") + ".")

    if args.csv:
        print(f"\nFull report written to {args.csv}")


if __name__ == "__main__":
    main()
