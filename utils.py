import matplotlib.pyplot as plt
import numpy as np
from io import BytesIO
import base64

def generate_chart(labels, values, title):
    plt.figure(figsize=(8, 5))
    plt.bar(labels, values, color='skyblue')
    plt.title(title)
    plt.xticks(rotation=45)
    plt.tight_layout()

    img = BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode()
    plt.close()
    return f"data:image/png;base64,{plot_url}"