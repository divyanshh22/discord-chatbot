# Audio folder

Drop audio files here (.mp3, .m4a, .wav, .ogg, .opus, .flac, .aac, .webm, .mp4).

Then in Discord use:
- `/audio list`  -> list available files
- `/audio play`  -> pick a file (or random) and play it in your voice channel
- `/audio stop`  -> stop playback
- `/audio leave` -> disconnect the bot from voice

Notes:
- The bot needs Connect + Speak permission in the voice channel.
- The host needs `ffmpeg` installed, and the `PyNaCl` package (already in requirements.txt).
- Files must be committed to the repo to survive a Render redeploy (ephemeral disk).
