"""Bundled phone artwork for the editor's HTML/CSS interface."""
from ui_resources import resource_manifest, resource_path

def resources():
    return resource_manifest('phone')

def resource_file(name):
    return resource_path('phone', name)
