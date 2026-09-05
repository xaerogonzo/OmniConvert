"""Format vocabulary, in a Tk-free module.

`ui/constants.py` used to own these, but importing anything from `omniconvert.ui`
executes its `__init__`, which pulls in the CustomTkinter panels. Settings
validation needs the same vocabulary and must stay importable with no display,
so the shared names live here and `ui.constants` re-exports them.
"""

#: Input extensions the queue will accept.
SUPPORTED = {".pdf", ".docx", ".epub", ".md", ".txt"}

#: Target formats offered in the UI, in menu order.
FORMATS = ["PDF", "DOCX", "EPUB", "MD", "TXT"]

#: Targets that can only be produced by pandoc, in Standard mode.
PANDOC_TARGETS = {"docx", "epub", "txt"}

#: Conversion modes, as shown on the segmented button.
MODES = ["Standard", "High-Fidelity"]
