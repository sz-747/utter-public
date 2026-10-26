"""
LLM role package - role settings files only

Keep only role settings files in this folder; do not put other Python files here.
"""

# This file is intentionally empty; it only marks LLM as a Python package. Do not delete it.



"""
# Role settings template

# Basic info
name: str = ""                               # Role display name
match: bool = True                           # Enable prefix matching
process: bool = True                         # Enable LLM processing

# API settings
provider: str = 'ollama'                     # API provider
api_url: str = ''                            # API URL
api_key: str = ''                            # API key
model: str = 'gemma3:4b'                     # Model name

# Context
max_context_length: int = 4096               # Maximum context length (tokens)

# Features
enable_thinking: bool = False                # Enable thinking (Ollama only)
enable_history: bool = False                 # Keep conversation history
enable_hotwords: bool = False                # Read matching hotwords
enable_rectify: bool = False                 # Read matching correction history
enable_read_selection: bool = False          # Read the selected text (via Ctrl+C)
selection_max_length: int = 1000             # Maximum length of the selected text

# Output
output_mode: str = 'typing'                  # Output mode: 'typing' or 'toast' (type the text or show a pop-up)

# Toast window
toast_initial_width: float = 0.5             # Initial toast width (0.5 = 50% of the screen width)
toast_initial_height: int = 0                # Initial toast height (0 means automatic)
toast_font_family: str = ''                  # Toast font (empty means the system default)
toast_font_size: int = 16                    # Toast font size
toast_font_color: str = 'white'              # Toast font color
toast_bg_color: str = '#075077'              # Toast background color
toast_duration: int = 3000                   # How long the toast stays (milliseconds)
toast_editable = True                  # Editable (after Markdown rendering)

# Generation
temperature: float = 0.7                     # Temperature (0-2)
top_p: float = 0.9                           # Top-p sampling
max_tokens: int = 1024                       # Maximum output tokens (0 means the model's default)
stop: str = ''                               # Stop sequence

# Advanced
extra_options: Dict[str, Any] = field(default_factory=dict)  # Extra API parameters

# Prompt prefixes
prompt_prefix_hotwords: str = 'Hotwords: '               # Prefix for the hotword list
prompt_prefix_rectify: str = 'Correction history: '      # Prefix for the correction history
prompt_prefix_selection: str = 'Selected text: '         # Prefix for the selected text
prompt_prefix_input: str = 'User input: '                # Prefix for the user's dictation

# System Prompt
system_prompt: str = ''                      # System prompt


"""
