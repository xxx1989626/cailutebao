import qrcode
import io
import base64
from flask import jsonify,url_for
from flask_login import login_required

from . import hr_bp
from utils import perm

# ==================== 生成二维码的接口 ====================
@hr_bp.route('/generate_qr')
@login_required
@perm.require('hr.edit')
def generate_qr():
    base_url = "https://cailutebao.top"
    target_url = base_url + url_for('hr.self_register')
    
    # 生成二维码
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(target_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    # 转为Base64
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_b64 = base64.b64encode(buf.getvalue()).decode()
    
    return jsonify({'success': True, 'qr_code': qr_b64, 'url': target_url})