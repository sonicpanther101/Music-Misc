# use ffmpeg to turn all audio files in a folder into flac files
import os
import subprocess

audio_types = ('.mp3', '.wav', '.ogg', '.opus', '.m4a')

directory = "C:\\Users\\Adam\\Documents\\Soulseek Downloads\\complete\\djelvigilante\\(2020-09-25) City of Angels (Neanderthal Remix)"

# get all audio files in a folder
audio_files = [f for f in os.listdir(directory) if any(f.endswith(t) for t in audio_types)]
print(audio_files)

# convert each audio file to flac
for audio_file in audio_files:
    # the output filename is the same as the input filename but with a different extension
    output_filename = audio_file.rsplit('.', 1)[0] + '.flac'
    print(output_filename)

    # run ffmpeg to convert the audio file
    subprocess.run(['ffmpeg', '-i', os.path.join(directory, audio_file), os.path.join(directory, output_filename)])

# delete the original audio files
# for audio_file in audio_files:
#     os.remove(audio_file)

print('All audio files have been converted to flac.')