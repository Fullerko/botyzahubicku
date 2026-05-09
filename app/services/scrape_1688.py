import requests
from google.cloud import vision
from PIL import Image
from io import BytesIO

# Funkce pro stažení obrázku a ověření velikosti
def download_image(url):
    response = requests.get(url)
    img = Image.open(BytesIO(response.content))
    if img.size[0] >= 800 and img.size[1] >= 800:
        return img
    return None

# Funkce pro analýzu obrázku pomocí Google Vision API
def analyze_image(image_url):
    client = vision.ImageAnnotatorClient()
    image = vision.Image()
    image.source.image_uri = image_url
    response = client.label_detection(image=image)
    labels = response.label_annotations
    return labels