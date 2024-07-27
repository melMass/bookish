import os

try:
    import hwebserver
except ImportError:
    hwebserver = None
try:
    import waitress
except ImportError:
    waitress = None


def default_houdini_app(override_config=None, config_file=None):
    app = get_houdini_app(override_config=override_config,
                          config_file=config_file,
                          auto_compile_scss=False,
                          bgindex=False)
    app.app_context().push()
    return app


def get_houdini_app(override_config=None, use_houdini_path=True,
                    config_file=None, auto_compile_scss=None, bgindex=None,
                    logfile=None, loglevel=None, debug=None):
    from bookish import flaskapp, flasksupport

    app = flaskapp.bookishapp
    if override_config:
        app.config.update(override_config)
    else:
        flasksupport.setup_config(app, config_file=config_file,
                                  use_houdini_path=use_houdini_path)

    if os.environ.get("HOUDINI_DISABLE_BACKGROUND_HELP_INDEXING"):
        app.config["USE_SOURCE_INDEX"] = True

    # Override certain configuration with keyword args if they're not None
    if auto_compile_scss is not None:
        app.config["AUTO_COMPILE_SCSS"] = auto_compile_scss
    if bgindex is not None:
        app.config["ENABLE_BACKGROUND_INDEXING"] = bgindex
    if logfile:
        app.config["LOGFILE"] = logfile
    if loglevel:
        app.config["LOGLEVEL"] = loglevel
    if debug is not None:
        app.config["DEBUG"] = debug

    # Set up app
    flasksupport.setup(app)

    return app


def start_server(host="0.0.0.0", port=8080, override_config=None,
                 debug=False, bgindex=None,
                 config_file=None, use_houdini_path=True,
                 auto_compile_scss=None, use_waitress=False,
                 **kwargs):
    app = get_houdini_app(override_config=override_config,
                          use_houdini_path=use_houdini_path,
                          config_file=config_file,
                          auto_compile_scss=auto_compile_scss,
                          bgindex=bgindex)

    if use_waitress and waitress:
        print("Using Waitress...")
        from paste.translogger import TransLogger
        return waitress.serve(TransLogger(app), host=host, port=port)
    elif hwebserver:
        print("Using hwebserver...")
        from houdinihelp.api import start_hwebserver
        return start_hwebserver(app, host, port, allow_system_port=False,
                                in_background=False)
    else:
        print("Using Flask...")
        return app.run(host=host, port=port, debug=debug, threaded=True,
                       **kwargs)


def start_dev_server(host="0.0.0.0", port=8080, debug=True, bgindex=None,
                     config_file=None, **kwargs):
    return start_server(host, port, debug=debug, bgindex=bgindex,
                        config_file=config_file, **kwargs)


def start_app_server(host="0.0.0.0", port=48626, debug=None, bgindex=None,
                     config_file=None, **kwargs):
    return start_server(host, port, debug=debug, bgindex=bgindex,
                        config_file=config_file, **kwargs)


if __name__ == "__main__":
    start_dev_server(config_file="$SHH/dev.cfg",
                     debug=True,
                     bgindex=True,
                     use_houdini_path=False,
                     auto_compile_scss=True,
                     use_waitress=False)


