# routes/__init__.py
# 注册所有蓝图到应用

def register_blueprints(app):
    from .main import main_bp
    from .auth import auth_bp
    from .hr import hr_bp
    from .asset import asset_bp
    from .fund import fund_bp
    from .permission import permission_bp
    from .scheduling import scheduling_bp, SCHEDULING_PERMISSIONS
    from .dorm import dorm_bp
    from .notification import notification_bp
    from .trip import trip_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(hr_bp)
    app.register_blueprint(asset_bp)
    app.register_blueprint(fund_bp)
    app.register_blueprint(permission_bp)
    app.register_blueprint(scheduling_bp)
    app.register_blueprint(dorm_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(trip_bp)
