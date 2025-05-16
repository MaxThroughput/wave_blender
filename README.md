# wave_blender

**wave_blender** is a tool for importing, blending, and exporting `.wav` files into 16-bit PCM files, optimized for use with UDO synthesizers and any other hardware or software that supports 4096-sample waveforms.

## Features

- **Wave Import:** Load 1, 2, 4, or 8 `.wav` files simultaneously.
- **Wave Blending:** Symmetrically consolidate multiple waves using advanced blending and Fourier transform algorithms.
- **Auditioning:** Preview and audition your blended waves before export.
- **Export:** Output ready-to-use 16-bit PCM files with exactly 4096 samples, compatible with UDO synthesizers and similar devices.

## Usage

1. **Import Waves:** Select up to 8 `.wav` files to blend.
2. **Blend:** The application automatically blends and consolidates the waves using its internal algorithms.
3. **Audition:** Listen to the result directly within the app.
4. **Export:** Save the final 16-bit PCM file for use in your synthesizer.

## Requirements

- Windows (pre-built executable included)
- No installation required; simply run `wave_blender_0.4.exe`

## Known Issues
- Extract Clean 4096-Sample Window is not working as intended. Please disable for now.

## License

See [frozen_application_license.txt](frozen_application_license.txt) for license information.

---

*For questions or support, please open an issue or contact the maintainer.*