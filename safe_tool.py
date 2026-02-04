import functools
import traceback

def safe_tool(func):
    """
    Decorator to prevent tool failures from crashing the application.
    Returns a clean JSON error object if an exception occurs.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Print traceback for debugging logs, but don't crash
            print(f"!!! SAFE TOOL CAUGHT ERROR in {func.__name__} !!!")
            traceback.print_exc()

            # Return standard error format for the LLM
            return {
                "error": str(e),
                "error_type": type(e).__name__,
                "advice": "The tool failed to execute. Please try again with different parameters or inform the user."
            }
    return wrapper
