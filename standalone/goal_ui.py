"""Bundled goal artwork for the editor's HTML/CSS interface."""
from ui_resources import resource_manifest, resource_path

def resources():
    return resource_manifest('goal')

def resource_file(name):
    return resource_path('goal', name)
