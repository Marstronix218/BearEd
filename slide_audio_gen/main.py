import os
import sys
from transformers import pipeline
from datasets import load_dataset
import soundfile as sf
import torch
import numpy as np
import requests
import json
import re
from PIL import Image, ImageDraw, ImageFont
import wave

print('initializing..')
AUDIO_PATH = '/audio/'
SLIDE_PATH = '/slides/'
GAIN_FACTOR = 3
# first argument is the txt file with the transcript
topic = sys.argv[1]

# audio synthesis
synthesiser = pipeline("text-to-speech", "microsoft/speecht5_tts")

embeddings_dataset = load_dataset("Matthijs/cmu-arctic-xvectors", split="validation")
speaker_embedding = torch.tensor(embeddings_dataset[7306]["xvector"]).unsqueeze(0)


# get the open AI API key by reading config.json
with open('config.json', 'r') as file:
    config = json.load(file)

OPENAI_API_KEY = config['OPENAI_API_KEY']


def speak(text, filename):
    GAIN_FACTOR = 3  # Adjust this value to increase or decrease the volume
    current_path = os.getcwd()
    file_path = current_path + AUDIO_PATH + filename

    # check audio folder
    if not os.path.exists(current_path + AUDIO_PATH):
        os.makedirs(current_path + AUDIO_PATH)

    # cut text into sentences
    text_pieces = []

    # find number of sentences
    num_sentences = len(re.findall(r'[.!?]', text))
    while len(text) > 0:
        # look for . or ? or ! to cut the text
        next_dot = text.find(".")
        next_question = text.find("?")
        next_exclamation = text.find("!")
        
        endings = []
        for end in [next_dot, next_question, next_exclamation]:
            if end != -1:
                endings.append(end)
        
        if len(endings) == 0:
            # no more sentence endings, add the rest of the text
            text_pieces.append(text)
            break
        
        end = min(endings)+1

        # get the sentence
        sentence = text[:end].strip()

        # remove the sentence from the text
        text = text[end:]

        text_pieces.append(sentence)

        

    
    
    for i, piece in enumerate(text_pieces):
        
        # print the progress
        print(f'Processing sentence {i+1}/{num_sentences}', end='\r')

        speech = synthesiser(piece, forward_params={"speaker_embeddings": speaker_embedding})
        increased_volume_audio = np.clip(speech["audio"] * GAIN_FACTOR, -1.0, 1.0)
        sf.write(file_path + "_part_" + str(i) + ".wav", increased_volume_audio, samplerate=speech["sampling_rate"])

def get_JSON_from_transcript(transcript):
    print('Using OpenAI to convert the transcript to a JSON format...')
    prompt = """
You are an experienced programmer and presenter. You have the following transcript to present. 
make sure to change abbreviations to full words. Dont use any punctuation.
Convert them into JSON with the following format:
{
slides:[
    { 
    slide: 1,
    line: <Things to say>,
    title: <summary of things to say in 5 words at most>
    },
    {
    slide: <slide number>,
    line: <Things to say>,
    title: <summary of things to say in 5 words at most>
    }
]
}

Here is the transcript

"""

    endpoint =  "https://api.openai.com/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + OPENAI_API_KEY,
    }

    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": transcript
            }
        ]
    }

    response = requests.post(endpoint, json=data, headers=headers)
    response_data = response.json()
    slides_JSON = response_data['choices'][0]['message']['content']
    slides_JSON = json.loads(slides_JSON)

    return slides_JSON

def covert_trascript_to_audio(slides_JSON):
    print('Transcript converted to JSON, starting to convert to audio...')
    for slide in slides_JSON['slides']:
        mytext = slide['line']
        print('Converting slide ' + str(slide['slide']) + ' to audio...')
        speak(mytext, "slide" + str(slide['slide']))

    print("All slides have been converted to audio")

def generate_slides(slides_JSON):
    """
    using the title from the JSON, we will generate an image with that title
    black text on white background
    """
    slide_path = os.getcwd() + SLIDE_PATH

    if not os.path.exists(slide_path):
        os.makedirs(slide_path)
    
    print('Generating slides...')
    for slide in slides_JSON['slides']:
        title = slide['title']
        slide_num = slide['slide']

        FONT_SIZE = 60
        SLIDE_HEIGHT = 600
        SLIDE_WIDTH = 800

        # create an image with the title
        img = Image.new('RGB', (SLIDE_WIDTH, SLIDE_WIDTH), color = 'white')

        # draw big text in the middle
        fnt = ImageFont.truetype('./fonts/times new roman bold.ttf', FONT_SIZE)
        
        d = ImageDraw.Draw(img)
        

        text_width, text_height = d.textlength(title, font=fnt), FONT_SIZE

        # if the title is too long, cut it
        cut_title = ""
        if text_width > SLIDE_WIDTH:
            while text_width > SLIDE_WIDTH:
                # add last word to the cut_title
                last_word = title.split()[-1]
                title = title[:-len(last_word)]
                cut_title = last_word + cut_title

                text_width, text_height = d.textlength(title, font=fnt), FONT_SIZE
        


        d.text(((SLIDE_WIDTH - text_width)/2,(SLIDE_HEIGHT-text_height)/2), title, font=fnt, fill='black')
        d.text(((SLIDE_WIDTH - text_width)/2,(SLIDE_HEIGHT+text_height)/2 +FONT_SIZE+10), cut_title, font=fnt, fill='black')
        
        img.save(slide_path+ 'slide_' + str(slide_num) + '.png')

    print('All slides have been generated')

def generate_transcript(topic):
    prompt = f"""
You are an experienced programmer and presenter. You are giving a presentation about {topic}.
You have to generate a transcript for the presentation. The transcript should be clear and concise.
Assume your audience is highschool students.  
Each slide must have at least 8 sentences. Make the presentation style engaging by asking rhetorical questions and using humor.
If you use humor, keep it mind it will be read by a text-to-speech engine.
it should be in the following format:

Slide 1:
<things to say>

Slide 2:
<things to say>

Create at least 5 slides. but no more than 10 slides. and DO NOT USE ANY ABBREVIATIONS.
"""

    endpoint =  "https://api.openai.com/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + OPENAI_API_KEY,
    }

    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    response = requests.post(endpoint, json=data, headers=headers)
    response_data = response.json()
    transcript = response_data['choices'][0]['message']['content']

    return transcript

def merge_audio_files():
    """
    merge all the audio files into one for each slide
    """
    print('Merging audio files...')
    # get the audio files
    audio_files = os.listdir(os.getcwd() + AUDIO_PATH)
    audio_files = sorted(audio_files)

    print(audio_files)
    slides = {}
    for file in audio_files:
        slide_name = file.split('_')[0]

        if slide_name not in slides:
            slides[slide_name] = []
        
        audio = wave.open(os.getcwd() + AUDIO_PATH + file, 'rb')
        # get the audio data
        audio_params = audio.getparams()
        audio_data = audio.readframes(audio.getnframes())

        slides[slide_name].append((audio_params,audio_data))
        audio.close()
    
    # if merged folder does not exist, create it
    if not os.path.exists(os.getcwd() + AUDIO_PATH + 'merged/'):
        os.makedirs(os.getcwd() + AUDIO_PATH + 'merged/')

    # create a new audio file for each slide
    for slide in slides:
        audio_data = slides[slide]
        new_audio = wave.open(os.getcwd() + AUDIO_PATH +'merged/'+ slide + '.wav', 'wb')
        
        new_audio.setparams(audio_data[0][0])
        for data in audio_data:
            new_audio.writeframes(data[1])
        
        new_audio.close()

    print('All audio files have been merged')

def generate_video():
    """
    generate a video from the slides and audio
    using the merged audio files, and slides, we can create a simple video
    """
    print('Generating video...')
    # get the audio files
    audio_files = os.listdir(os.getcwd() + AUDIO_PATH + 'merged/')
    audio_files = sorted(audio_files)

    # get the slides
    slide_files = os.listdir(os.getcwd() + SLIDE_PATH)
    slide_files = sorted(slide_files)

    # create video in the video folder
    if not os.path.exists(os.getcwd() + '/video/'):
        os.makedirs(os.getcwd() + '/video/')
    
    video_files = []
    # create a video for each slide
    for i, slide in enumerate(slide_files):
        print(f'Creating video for slide {i+1}/{len(slide_files)}', end='\r')
        slide_path = os.getcwd() + SLIDE_PATH + slide
        audio_path = os.getcwd() + AUDIO_PATH + 'merged/' + audio_files[i]
        video_path = os.getcwd() + '/video/' + slide.split('.')[0] + '.mp4'
        

        # escape the spaces in the path
        slide_path = slide_path.replace(' ', '\\ ')
        audio_path = audio_path.replace(' ', '\\ ')
        video_path = video_path.replace(' ', '\\ ')

        video_files.append(video_path)


        command = f'ffmpeg -loop 1 -i {slide_path} -i {audio_path} -shortest {video_path}'

        os.system(command)

    # create a list of videos to merge
    video_list = ''
    for video in video_files:
        video_list += 'file ' + video + '\n'

    with open(os.getcwd() + '/video/'+'video_list.txt', 'w') as file:
        file.write(video_list)
    
    video_list_path = os.getcwd() + '/video/'+'video_list.txt'
    final_video_path = os.getcwd() + '/presentation.mp4'
    
    video_list_path = video_list_path.replace(' ', '\\ ')
    final_video_path = final_video_path.replace(' ', '\\ ')

    command = f'ffmpeg -f concat -safe 0 -i {video_list_path} -c copy {final_video_path}'
    os.system(command)

def reset():
    print('Cleaning up...')
    # Allow preserving artifacts for downstream pipelines via env vars
    keep_slides = os.getenv('KEEP_SLIDES', '0') == '1'

    # remove the audio files (except merged/, handled below)
    audio_root = os.path.join(os.getcwd(), AUDIO_PATH.strip('/')) + '/'
    if os.path.exists(audio_root):
        audio_files = os.listdir(audio_root)
        for file in audio_files:
            path = os.path.join(audio_root, file)
            if not os.path.isdir(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    # optionally remove the slides
    slides_root = os.path.join(os.getcwd(), SLIDE_PATH.strip('/')) + '/'
    if not keep_slides and os.path.exists(slides_root):
        slide_files = os.listdir(slides_root)
        for file in slide_files:
            try:
                os.remove(os.path.join(slides_root, file))
            except Exception:
                pass

    # remove the merged audio files and directory
    merged_root = os.path.join(audio_root, 'merged')
    if os.path.exists(merged_root):
        try:
            merged_files = os.listdir(merged_root)
            for file in merged_files:
                try:
                    os.remove(os.path.join(merged_root, file))
                except Exception:
                    pass
            os.rmdir(merged_root)
        except Exception:
            pass

    # remove the per-slide video files
    video_root = os.path.join(os.getcwd(), 'video')
    if os.path.exists(video_root):
        try:
            video_files = os.listdir(video_root)
            for file in video_files:
                try:
                    os.remove(os.path.join(video_root, file))
                except Exception:
                    pass
        except Exception:
            pass

    print(f"Cleanup complete. Slides preserved: {keep_slides}")


def main():
    print('starting')

    print(f'Generating transcript for presentation about {topic}...')

    transcript = generate_transcript(topic)

    slides_JSON = get_JSON_from_transcript(transcript)

    generate_slides(slides_JSON)
    covert_trascript_to_audio(slides_JSON)

    merge_audio_files()

    generate_video()

    reset()

    print('All done! Presentation video has been generated')
    exit(0)


if __name__ == '__main__':
    main()
