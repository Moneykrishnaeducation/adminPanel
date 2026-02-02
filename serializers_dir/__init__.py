# Serializers package - contains both main serializers and chat-specific serializers
# Import everything from the parent serializers.py file
import sys
import os
from pathlib import Path

# Get path to the parent serializers.py
parent_dir = Path(__file__).parent.parent
serializers_py_path = parent_dir / 'serializers.py'

# Read and execute the serializers.py file to get all its exports
serializers_globals = {}
with open(serializers_py_path, 'r') as f:
    exec(f.read(), serializers_globals)

# Export all classes from serializers.py
for name, obj in serializers_globals.items():
    if not name.startswith('_'):
        globals()[name] = obj

# Also import chat-specific serializers
from adminPanel.serializers.chat_serializers import ChatMessageSerializer, ManagerChatMessageListSerializer

__all__ = ['ChatMessageSerializer', 'ManagerChatMessageListSerializer']
