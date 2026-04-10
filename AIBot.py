import speech_recognition as sr
import RPi.GPIO as GPIO
import time

BUTTON_PIN = 16

GPIO.setmode(GPIO.BCM)
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

r = sr.Recognizer()

try:
  with sr.Microphone() as source:
    print("Pronto (tieni premuto per parlare)")

    while True:
      # Aspetta che premi il bottone
      if GPIO.input(BUTTON_PIN) == 0:
        print("Registrazione...")

        frames = []
        start_time = time.time()

        # Continua a registrare finché tieni premuto
        while GPIO.input(BUTTON_PIN) == 0:
          audio = r.listen(source, phrase_time_limit=0.5)
          frames.append(audio)

        print("Fine registrazione")

        # Unisci i pezzi audio
        audio_data = sr.AudioData(
          b"".join([f.get_raw_data() for f in frames]),
          frames[0].sample_rate,
          frames[0].sample_width
        )

        try:
          text = r.recognize_google(audio_data)
          print("Text:", text)
        except:
          print("Non ho capito")

        time.sleep(0.5)  # debounce leggero

finally:
  GPIO.cleanup()