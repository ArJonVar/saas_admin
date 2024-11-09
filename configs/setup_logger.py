import logging
import logging.handlers

class ColoredFormatter(logging.Formatter):
    # Define your colors
    COLORS = {
        logging.DEBUG: "\033[0;33m",   # Yellow
        logging.INFO: "\033[0;32m",    # Green
        logging.WARNING: "\033[0;35m", # Orange (using purple as closest alternative)
        logging.ERROR: "\033[0;31m",   # Red
        logging.CRITICAL: "\033[1;31m" # Bright Red
    }
    
    def format(self, record):
        # Apply color to the log level name
        log_color = self.COLORS.get(record.levelno)
        reset_color = "\033[0m"
        
        record.levelname = f"{log_color}{record.levelname}{reset_color}"
        
        # Apply color to the message as well (optional)
        record.msg = f"{log_color}{record.msg}{reset_color}"
        
        return super().format(record)

def setup_logger(name=None, level=logging.INFO):
    """
    Set up a logger with the specified name and log level, with color output.
    
    :param name: The name of the logger (usually the __name__ of the module using it).
    :param level: The logging level (e.g., logging.INFO, logging.DEBUG).
    :return: Configured logger.
    """
    # Create a custom logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent log messages from propagating to the root logger
    logger.propagate = False

    # Remove any existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create handlers
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    # Create a colored formatter and add it to the console handler
    formatter = ColoredFormatter(
        '%(asctime)s [%(levelname)s] %(filename)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)

    # Add handlers to the logger
    logger.addHandler(console_handler)

    return logger
