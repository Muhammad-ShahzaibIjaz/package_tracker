import os
from flask import Flask, request, jsonify, send_file
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.graphics.barcode import code128
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from PyPDF2 import PdfReader, PdfWriter
from io import BytesIO
from pystrich.datamatrix import DataMatrixEncoder
from datetime import datetime
import zipfile

app = Flask(__name__)


class USPSLabelGenerator:
    def __init__(self, template_path):
        self.template_path = template_path
        
    def generate_label(self, output_path, shipping_data):
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)
        
        # Set font for all text elements
        can.setFont("Helvetica", 9)
        
        # Add ship date (assuming current date for now)
        current_date = datetime.now().strftime("%d/%m/%Y")
        can.drawString(188, 318, f"Ship Date: {current_date}")
        
        # Add weight
        can.drawString(225, 304, f"Weight: {shipping_data.get('weight', 'N/A')} lb")
        
        # Add dimensions (if length, height, and width are provided)
        dimensions = f"{shipping_data.get('length', 'N/A')}x{shipping_data.get('height', 'N/A')}x{shipping_data.get('width', 'N/A')}"
        can.drawString(186, 293, f"Dimensions: {dimensions}")
        
        # Add sender information
        can.setFont("Helvetica", 8)
        can.drawString(10, 318, f"{shipping_data.get('fromName', 'N/A')}")
        can.drawString(10, 308, f"{shipping_data.get('fromAddress', 'N/A')}")
        if shipping_data.get('fromAddress2'):
            can.drawString(10, 298, f"{shipping_data['fromAddress2']}")
            can.drawString(10, 288, f"{shipping_data.get('fromCity', 'N/A')} {shipping_data.get('fromState', 'N/A')} {shipping_data.get('fromZip', 'N/A')}")
        else:
            can.drawString(10, 298, f"{shipping_data.get('fromCity', 'N/A')} {shipping_data.get('fromState', 'N/A')} {shipping_data.get('fromZip', 'N/A')}")
        
        
        # Add recipient information
        can.setFont("Helvetica", 8)
        can.drawString(10, 240, "SHIP TO:")
        can.drawString(50, 238, f"{shipping_data.get('toName', 'N/A')}")
        can.drawString(50, 228, f"{shipping_data.get('toAddress', 'N/A')}")
        if shipping_data.get('toAddress2'):
            can.drawString(50, 218, f"{shipping_data['toAddress2']}")
            # Add recipient city, state, and zip with large font
            can.setFont("Helvetica", 12.5)
            can.drawString(50, 206, f"{shipping_data.get('toCity', 'N/A')} {shipping_data.get('toState', 'N/A')} {shipping_data.get('toZip', 'N/A')}")
        else:
            # Add recipient city, state, and zip with large font
            can.setFont("Helvetica", 12.5)
            can.drawString(50, 214, f"{shipping_data.get('toCity', 'N/A')} {shipping_data.get('toState', 'N/A')} {shipping_data.get('toZip', 'N/A')}")
        
        # Generate Data Matrix Code using pystrich
        tracking_number = shipping_data.get('tracking_number', 'N/A')
        tracking_number = tracking_number.replace(" ", "")
        gs_char = chr(29)
        barcode_data_code = f"420{shipping_data.get('toZip', 'N/A')}{gs_char}{tracking_number}"
        data_matrix = DataMatrixEncoder(barcode_data_code)
        data_matrix_path = "data_matrix.png"
        data_matrix.save(data_matrix_path)
        
        # Add the Data Matrix image to the PDF
        data_matrix_img = ImageReader(data_matrix_path)
        can.drawImage(data_matrix_img, 7, 200, width=35, height=35)
        can.drawImage(data_matrix_img, 245, 5, width=35, height=35)

        # Add tracking number and barcode
        can.setFont("Helvetica-Bold", 12)
        
        # Generate the barcode in format of GS1-128 format
        barcode = code128.Code128(barcode_data_code, barHeight=60, barWidth=1)
        
        # Draw the barcode on the canvas
        barcode.drawOn(can, 9, 71)
        
        # Add tracking number below barcode
        def format_tracking_number(tracking_number):
            tracking_number = tracking_number.replace(" ", "")
            chunks = [tracking_number[i:i+4] for i in range(0, len(tracking_number), 4)]
            return ' '.join(chunks)


        formatted_tracking_number = format_tracking_number(tracking_number)
        can.drawString(60, 55, formatted_tracking_number)

        can.save()
        
        packet.seek(0)
        
        new_pdf = PdfReader(packet)
        
        existing_pdf = PdfReader(self.template_path)
        
        output = PdfWriter()
        
        page = existing_pdf.pages[0]
        page.merge_page(new_pdf.pages[0])
        output.add_page(page)
        
        with open(output_path, "wb") as output_file:
            output.write(output_file)
            
        return output_path


@app.route('/v1/generate-labels', methods=['POST'])
def generate_labels():
    payload = request.json
    
    if not isinstance(payload, list):
        return jsonify({"error": "Payload must be a list of shipping data objects"}), 400
    
    output_folder = "generated_labels"
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    template_path = "sample_template.pdf"
    generator = USPSLabelGenerator(template_path)

    generated_files = []
    for shipping_data in payload:
        tracking_number = shipping_data.get('tracking_number', 'unknown')
        output_path = os.path.join(output_folder, f"{tracking_number}.pdf")
        generator.generate_label(output_path, shipping_data)
        generated_files.append(output_path)
    


    if len(generated_files) == 1:
        return send_file(generated_files[0], as_attachment=True, download_name=f"{tracking_number}.pdf")
    
    zip_filename = "generated_labels.zip"
    with zipfile.ZipFile(zip_filename, 'w') as zipf:
        for file in generated_files:
            zipf.write(file, os.path.basename(file))
    
    return send_file(zip_filename, as_attachment=True, download_name="generated_labels.zip")
    

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
