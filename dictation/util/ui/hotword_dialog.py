# coding: utf-8
"""
Add-dictionary-words dialog module

Provides the HotwordDialog class, which shows the "Add dictionary words" dialog.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from .dialogs import (
    create_modal_dialog,
    DialogResult,
    wait_window,
)
from .toast_constants import DEFAULT_FONT_FAMILY
from . import logger



class HotwordDialog:
    """
    Add-dictionary-words dialog

    Shows a modal dialog where the user enters:
    - Dictionary words (matched during speech recognition)

    When the user clicks OK, the words are saved to hot.txt.
    """

    def __init__(self, parent: tk.Tk = None):
        """
        Initialize the dialog

        Args:
            parent: Parent window (the Tk root); if None, a hidden Tk is created
        """
        if parent is None:
            parent = tk.Tk()
            parent.withdraw()  # Hide the root window

        self.parent = parent
        self.result: Optional[DialogResult] = None

    def show(
        self,
        default_text: str = "",
        title: str = "Add dictionary words",
        width: int = 800
    ) -> DialogResult:
        """
        Show the dialog

        Args:
            default_text: Text to fill in at the start
            title: Dialog title
            width: Dialog width (pixels), default 800

        Returns:
            DialogResult:
            - result.confirmed: Whether the user clicked OK
            - result.data: {'hotword': str}
        """
        # Create the dialog window
        dialog = create_modal_dialog(
            title=title,
            width=width,
            height=180,
            resizable=False,
            withdraw=True
        )

        # Create the container
        main_frame = ttk.Frame(dialog, padding=(20, 15, 20, 20))
        main_frame.pack(fill="both", expand=True)

        # Fonts
        label_font = (DEFAULT_FONT_FAMILY, 10, "bold")
        entry_font = (DEFAULT_FONT_FAMILY, 11)

        # Instructions
        ttk.Label(
            main_frame,
            text="Enter the words to add to the dictionary (one per line):",
            font=(DEFAULT_FONT_FAMILY, 9),
            foreground="#666666"
        ).pack(anchor="w", pady=(0, 10))

        # Word input (a Text widget so several words can be entered)
        text_widget = tk.Text(
            main_frame,
            height=3,
            font=entry_font,
            wrap="word",
            borderwidth=1,
            relief="solid",
            padx=5,
            pady=5
        )
        text_widget.pack(fill="x", pady=(0, 15))

        if default_text:
            text_widget.insert("1.0", default_text)

        # Buttons
        def on_confirm():
            """OK button callback"""
            value = text_widget.get("1.0", "end-1c").strip()

            # Check the input
            if not value:
                messagebox.showwarning("Nothing entered", "Enter at least one word.")
                return

            # Save the result and close the dialog
            self.result = DialogResult(
                confirmed=True,
                hotword=value
            )
            dialog.destroy()

        def on_cancel():
            """Cancel button callback"""
            self.result = DialogResult(confirmed=False)
            dialog.destroy()

        # Keyboard shortcuts
        dialog.bind("<Escape>", lambda e: on_cancel())
        dialog.bind("<Control-Return>", lambda e: on_confirm())

        # Button container
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))

        # OK button
        confirm_btn = tk.Button(
            button_frame,
            text="OK (Ctrl+Enter)",
            command=on_confirm,
            font=(DEFAULT_FONT_FAMILY, 9),
            bg="#4CAF50",
            fg="white",
            activebackground="#45a049",
            relief="flat",
            cursor="hand2",
            padx=15,
            pady=5
        )
        confirm_btn.pack(side="left", padx=5, ipady=0)

        # Cancel button
        cancel_btn = tk.Button(
            button_frame,
            text="Cancel (Esc)",
            command=on_cancel,
            font=(DEFAULT_FONT_FAMILY, 9),
            bg="#f44336",
            fg="white",
            activebackground="#da190b",
            relief="flat",
            cursor="hand2",
            padx=15,
            pady=5
        )
        cancel_btn.pack(side="left", padx=5, ipady=0)

        # Center and show
        dialog.update_idletasks()
        _center_window(dialog, width, dialog.winfo_reqheight())
        dialog.deiconify()
        dialog.lift()
        text_widget.focus_set()

        # Wait for the dialog to close
        wait_window(dialog)

        return self.result if self.result else DialogResult(confirmed=False)


def _center_window(window: tk.Toplevel, width: int, height: int) -> None:
    """Center a window on the screen"""
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    window.geometry(f"{width}x{height}+{x}+{y}")


def show_hotword_dialog(
    default_text: str = "",
    parent: tk.Tk = None,
    title: str = "Add dictionary words",
    width: int = 400
) -> DialogResult:
    """Show the add-dictionary-words dialog (convenience function)"""
    dialog = HotwordDialog(parent)
    return dialog.show(default_text, title, width)


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    res = show_hotword_dialog()
    print(f"Result: {res.confirmed}, Data: {res.data}")
