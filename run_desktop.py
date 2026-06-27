#!/usr/bin/env python3
"""UARTScope Pro — Desktop Entry Point"""
import sys
import os

# Add bundled resources to path
if getattr(sys, 'frozen', False):
    sys.path.insert(0, sys._MEIPASS)
    os.chdir(sys._MEIPASS)

from launch import main
main()
