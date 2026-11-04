# ffaca - FFMPEG Frame Accurate Cutter App
Pyhton based UI utility to preview frames and accurately cut clips from videos

Ever needed to cut a clip from a video without installing or opening an heavy video editor suite? Handy with ffmpeg command line, but can't quickly define the start and end times you want to clip? Then FFACA is for you!
With FFACA you can view all the keyframes and also navigate to non-keyframes and choose to cut at keyframes (lossless fast copy with no reencode), or choose a regular frame and accurate mode to cut precisely at that frame (requires reencode)

Either run the displayed ffmpeg command right in the UI with console view, or copy the command and further tweak the encoding options to run in a terminal window of your choosing!

Requirements:  
ffmpeg  
Python  
pillow  
python3-pil.imagetk (pillow-tk bindings)  
tkinterdnd2 (for drag&drop support)  

if no keyframes are shown, make sure you have installed python3-pil.imagetk:  
sudo apt install python3-pil.imagetk  

if you want drag&drop support install tkinterdnd2 in a virtual environment or at system level:
sudo pip install tkinterdnd2 --break-system-packages

keyboard shortcuts:  
[+] next frame  
[-] previous frame  
 

You are free to use, improve and otherwise modify this code and freely share your new code.
Made with the assistance of local LLM running on renewable energy. Use at your own risk. Gluten and lactose free. No animals were harmed in the making. If symptoms persist, consult your doctor.
