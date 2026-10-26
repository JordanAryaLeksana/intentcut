FPS = 30
# Scale using display aspect ratio (including non-square source pixels), then pad.
VIDEO_FILTER = (
    "setpts=PTS-STARTPTS,"
    "scale=720:1280:force_original_aspect_ratio=decrease:"
    "force_divisible_by=2:reset_sar=1,"
    "pad=720:1280:(ow-iw)/2:(oh-ih)/2:color=black,"
    "setsar=1,fps=30:start_time=0:eof_action=pass,"
    "tpad=stop_mode=clone:stop=-1,format=yuv420p"
)
