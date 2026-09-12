"""Bundled phone artwork for the editor's HTML/CSS interface."""
from ui_resources import resource_manifest, resource_path

def resources(game=None):
    return resource_manifest('phone', game)

def resource_file(name, game=None):
    return resource_path('phone', name, game)
