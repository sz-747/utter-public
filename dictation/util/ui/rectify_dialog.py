# coding: utf-8
"""
Correction dialog module

Provides the RectifyDialog class, which shows the "Add a correction" dialog.
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



class RectifyDialog:
    """
    Correction dialog

    Shows a modal dialog, filled in with the last recognition result, where the user edits:
    - Original text (the wrong text speech recognition produced)
    - Corrected text (the right text)

    When the user clicks OK, the correction is saved to hot-rectify.txt.

    Features:
        - Text boxes start one line high and grow with the content (1-10 lines)
        - No scrolling; the height adapts instead
        - The window height adjusts so the buttons stay visible
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
        recognition_text: str,
        title: str = "Add a correction",
        width: int = 600
    ) -> DialogResult:
        """
        Show the dialog

        Args:
            recognition_text: The last recognized text (filled into both text boxes)
            title: Dialog title
            width: Dialog width (pixels), default 600

        Returns:
            DialogResult:
            - result.confirmed: Whether the user clicked OK
            - result.data: {'original': str, 'corrected': str}
        """
        # Create the dialog window (initial height 200, adjusted later)
        dialog = create_modal_dialog(
            title=title,
            width=width,
            height=200,
            resizable=True,
            withdraw=True  # Hide the window first to avoid flicker
        )

        # Create the container
        main_frame = ttk.Frame(dialog, padding=(20, 15, 20, 25))
        main_frame.pack(fill="both", expand=True)

        # Keep the width for later height adjustments
        dialog_width = width

        # Instructions
        info_text = (
            "Edit the correction, starting from the last recognition result:\n"
            "• Original: the wrong text that was recognized\n"
            "• Corrected: the right text\n"
            "Click OK to save it to hot-rectify.txt, where LLM corrections can use it later."
        )
        info_label = ttk.Label(
            main_frame,
            text=info_text,
            font=(DEFAULT_FONT_FAMILY, 9),
            foreground="#666666"
        )
        # info_label.pack(anchor="w", pady=(0, 10))

        # Fonts
        text_font = (DEFAULT_FONT_FAMILY, 10)

        # Dynamic height adjustment
        def auto_resize_textbox(text_widget):
            """Resize a text box to its content (no scrolling)"""
            text_widget.update_idletasks()

            # Get the text
            content = text_widget.get("1.0", "end-1c")

            if not content:
                line_count = 1
            else:
                # Work out the real line count from the position of the last line
                # Try the index of the end of the text first
                try:
                    last_line_index = int(text_widget.index('end-1c').split('.')[0])
                    line_count = max(1, last_line_index)
                except:
                    # Fallback: estimate from the character count
                    # Assume about 50 characters per line (600px wide, 10pt font)
                    estimated_lines = max(1, len(content) // 50 + 1)
                    line_count = min(10, estimated_lines)

            # Limit to 1-10 lines
            new_height = max(1, min(10, line_count))
            current_height = text_widget.cget('height')

            if current_height != new_height:
                text_widget.configure(height=new_height)
                # Important: after changing the height, refresh the whole dialog layout
                # so the parent (main_frame) recalculates the height it needs
                dialog.update_idletasks()
                return True  # Height changed
            return False

        def update_dialog_height():
            """Resize the window to fit the content"""
            dialog.update_idletasks()
            new_height = main_frame.winfo_reqheight()
            dialog.geometry(f"{dialog_width}x{new_height}")

            return new_height  # Return the height that was set

        def on_text_change(event=None):
            height_changed = False
            height_changed |= auto_resize_textbox(original_text_widget)
            height_changed |= auto_resize_textbox(corrected_text_widget)

            if height_changed:
                # Update the window height
                new_height = update_dialog_height()
                dialog.geometry(f"{dialog_width}x{new_height}")

        def setup_text_widget(widget):
            widget.configure(yscrollcommand=lambda *args: None) # Turn off internal scrolling completely

            def _on_mod(event):
                if widget.edit_modified():
                    on_text_change()
                    widget.edit_modified(False) # Reset the modified flag

            widget.bind("<<Modified>>", _on_mod)

        # Original text box (starts one line high)
        ttk.Label(main_frame, text="Original:", font=(DEFAULT_FONT_FAMILY, 10, "bold")).pack(anchor="w")

        original_text_widget = tk.Text(
            main_frame,
            height=1,  # Starts at 1 line
            font=text_font,
            wrap="word",
            spacing1=2,
            spacing2=2,
            spacing3=2,
            borderwidth=1,
            relief="solid",
            padx=10,
            pady=10,
        )
        setup_text_widget(original_text_widget)

        # Anchored at the top left (like the toast; packing from the top keeps content from jumping)
        original_text_widget.pack(fill="x", pady=(5, 10))


        # Corrected text box (starts one line high)
        ttk.Label(main_frame, text="Corrected:", font=(DEFAULT_FONT_FAMILY, 10, "bold")).pack(anchor="w")

        corrected_text_widget = tk.Text(
            main_frame,
            height=1,  # Starts at 1 line
            font=text_font,
            wrap="word",
            spacing1=2,
            spacing2=2,
            spacing3=2,
            borderwidth=1,
            relief="solid",
            padx=10,
            pady=10,
        )
        setup_text_widget(corrected_text_widget)

        # Anchored at the top left (like the toast; packing from the top keeps content from jumping)
        corrected_text_widget.pack(fill="x", pady=(5, 10))

        # Fill both text boxes with the recognized text
        original_text_widget.insert("1.0", recognition_text)
        corrected_text_widget.insert("1.0", recognition_text)

        # Adjust the text box heights now (before binding events)
        dialog.update_idletasks()
        update_dialog_height()  # Return value not needed

        # Bind content change events
        for widget in [original_text_widget, corrected_text_widget]:
            widget.bind("<KeyRelease>", on_text_change)
            widget.bind("<ButtonRelease-1>", on_text_change)
            widget.bind("<KeyPress>", on_text_change)

        # Adjust the height again once the dialog is fully shown
        # after_idle makes sure this runs after all layout is done
        def final_adjustment():
            """Final height adjustment once the dialog is fully shown"""
            dialog.update_idletasks()

            # Recalculate the text box heights
            for widget in [original_text_widget, corrected_text_widget]:
                widget.update_idletasks()
                auto_resize_textbox(widget)

            # Update the window height and get the height that was set
            actual_height = update_dialog_height()

            # Center the window
            screen_width = dialog.winfo_screenwidth()
            screen_height = dialog.winfo_screenheight()

            # Work out the centered position
            x = (screen_width - dialog_width) // 2
            y = (screen_height - actual_height) // 2
            dialog.geometry(f"{dialog_width}x{actual_height}+{x}+{y}")

            # Show the window last (avoids flicker)
            dialog.deiconify()
            # Make sure the window is in front
            dialog.lift()

        # Run when the event loop is idle
        dialog.after_idle(final_adjustment)

        # Buttons
        def on_confirm():
            """OK button callback"""
            original_value = original_text_widget.get("1.0", "end-1c").strip()
            corrected_value = corrected_text_widget.get("1.0", "end-1c").strip()

            # Check the input
            if not original_value or not corrected_value:
                messagebox.showwarning("Nothing entered", "Fill in both the original and the corrected text.")
                return

            if original_value == corrected_value:
                result = messagebox.askyesno(
                    "Same text",
                    "The original and corrected text are the same. Save anyway?"
                )
                if not result:
                    return

            # Save the result and close the dialog
            self.result = DialogResult(
                confirmed=True,
                original=original_value,
                corrected=corrected_value
            )
            dialog.destroy()

        def on_cancel():
            """Cancel button callback"""
            self.result = DialogResult(confirmed=False)
            dialog.destroy()

        # Keyboard shortcuts (Esc cancels, Ctrl+Enter confirms)
        dialog.bind("<Escape>", lambda e: on_cancel())
        dialog.bind("<Control-Return>", lambda e: on_confirm())

        # Create the buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))

        # tk.Button instead of ttk.Button gives better control over the height
        confirm_btn = tk.Button(
            button_frame,
            text="OK (Ctrl+Enter)",
            command=on_confirm,
            width=15,
            height=1,
            font=(DEFAULT_FONT_FAMILY, 10),
            bg="#4CAF50",
            fg="white",
            activebackground="#45a049",
            relief="flat",
            cursor="hand2"
        )
        confirm_btn.pack(side="left", padx=5, ipady=0)  # ipady adds vertical inner padding

        cancel_btn = tk.Button(
            button_frame,
            text="Cancel (Esc)",
            command=on_cancel,
            width=15,
            height=1,
            font=(DEFAULT_FONT_FAMILY, 10),
            bg="#f44336",
            fg="white",
            activebackground="#da190b",
            relief="flat",
            cursor="hand2",
        )
        cancel_btn.pack(side="left", padx=5, ipady=0)  # ipady adds vertical inner padding

        update_dialog_height()  # Return value not needed

        # Focus the first text box
        original_text_widget.focus_set()

        # Wait for the dialog to close
        wait_window(dialog)

        logger.debug(
            f"Dialog closed: confirmed={self.result.confirmed if self.result else False}, "
            f"original={self.result.get('original', '')[:30] if self.result else ''}..."
        )

        return self.result if self.result else DialogResult(confirmed=False)


# ======================================================================
# Convenience function
# ======================================================================

def show_rectify_dialog(
    recognition_text: str,
    parent: tk.Tk = None,
    title: str = "Add a correction",
    width: int = 600
) -> DialogResult:
    """
    Show the correction dialog (convenience function)

    Args:
        recognition_text: The last recognized text
        parent: Parent window (optional)
        title: Dialog title
        width: Dialog width (pixels), default 600

    Returns:
        DialogResult
    """
    dialog = RectifyDialog(parent)
    return dialog.show(recognition_text, title, width)


if __name__ == "__main__":
    # Test code
    root = tk.Tk()
    root.withdraw()

    result = show_rectify_dialog(
        recognition_text="Meet me at the tree o'clock",
        parent=root,
        width=800
    )

    if result:
        print(f"Confirmed: {result.confirmed}")
        print(f"Original: {result.get('original')}")
        print(f"Corrected: {result.get('corrected')}")
    else:
        print("User cancelled")
