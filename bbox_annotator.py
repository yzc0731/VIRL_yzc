import os
import glob
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk
import json
import argparse
from typing import List, Dict, Tuple
from data_utils import get_panoids_from_json  # Assuming this function is defined in data_utils.py

class BoundingBoxAnnotator:
    def __init__(self, seed: int):
        """
        Initialize the Bounding Box Annotator
        
        Args:
            seed: Seed number to identify which dataset to use
        """
        self.seed = seed
        self.placedata_dir = f"./googledata/place{seed}"
        if not os.path.exists(self.placedata_dir):
            raise FileNotFoundError(f"Data directory {self.placedata_dir} does not exist. Please run the data download script first.")
        self.json_path = os.path.join(self.placedata_dir, "pano.json")        
        # Get all available panoids
        self.panoids = get_panoids_from_json(self.json_path)
        print(f"Found {len(self.panoids)} panoids in {self.placedata_dir}.")
        self.annotation_json_path = os.path.join(self.placedata_dir, "annotations.json")
        
        # Regular expression to extract image info
        self.image_pattern = re.compile(r"id_(.+?)_(front|right|left|back)\.jpg")
        self.view_label_list = ["front", "right", "left", "back"]
        
        # Initialize state variables
        self.current_panoid = None
        self.current_view = None
        self.current_image_path = None
        self.start_x = None
        self.start_y = None
        self.current_rect = None
        self.bboxes = {}  # Store all annotations
        self.mode = "single"  # Default mode: single or paired
        self.pair_index = 0  # Index for paired mode
        
        # Load existing annotations if any
        self.load_annotations()
        
        # Setup UI
        self.setup_ui()
    
    def get_images_for_panoid(self, panoid: str) -> Dict[str, str]:
        """Get all images for a specific panoid"""
        images = {}
        for label in self.view_label_list:
            image_file = os.path.join(self.placedata_dir, f"id_{panoid}_{label}.jpg")
            if os.path.exists(image_file):
                images[label] = image_file
            else:
                print(f"Warning: Image {image_file} does not exist.")
        return images

    def get_image_key(self, view: str, panoid: str = None) -> str:
        """Generate a unique key for an image by panoid and view, this is the key for self.bboxes"""
        if panoid is None: return f"{self.current_panoid}_{view}"
        return f"{panoid}_{view}"
    
    def load_annotations(self) -> None:
        """Load existing annotations if available"""
        if os.path.exists(self.annotation_json_path):
            with open(self.annotation_json_path, 'r') as f:
                self.bboxes = json.load(f)
            print(f"Loaded {len(self.bboxes)} existing annotations.")
        else:
            self.bboxes = {}
            print("No existing annotations found, starting fresh.")

    def save_annotations(self):
        """Save all annotations to file"""
        with open(self.annotation_json_path, 'w') as f:
            json.dump(self.bboxes, f, indent=2)
        print(f"Saved annotations to {self.annotation_json_path}")
        messagebox.showinfo("Saved", f"Annotations saved successfully!\n{len(self.bboxes)} images annotated.")
    
    def clear_current_annotations(self):
        """Clear annotations for the currently selected image"""
        if not self.current_image_path:
            messagebox.showwarning("Warning", "No image selected.")
            return
        
        image_key = self.get_image_key(view=self.current_view, panoid=self.current_panoid)
        if image_key in self.bboxes:
            if messagebox.askyesno("Confirm", f"Clear all annotations for Panoid {self.current_panoid}'s {self.current_view} view?"):
                del self.bboxes[image_key]
                # Refresh display
                self.select_image(self.current_panoid, self.current_view, self.current_image_path)
                if self.mode == "single":
                    self.load_panoid_images()
                else:
                    self.load_paired_images()
                self.status_var.set(f"Cleared annotations for Panoid {self.current_panoid}'s {self.current_view} view.")
        else:
            messagebox.showinfo("Info", "No annotations to clear.")
    
    def preview_boxes(self, image_key: str) -> None:
        """Show a preview of all bounding boxes and their descriptions for the current image"""
        if image_key not in self.bboxes or not self.bboxes[image_key]:
            messagebox.showinfo("Preview", "No bounding boxes on this image.")
            return
        
        # Create a new toplevel window
        preview_window = tk.Toplevel(self.root)
        preview_window.title(f"Bounding Boxes Preview - {image_key}")
        preview_window.geometry("640x480")
        
        # Create a frame with scrollbar
        frame = ttk.Frame(preview_window)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Add a treeview to display the data
        columns = ("Box ID", "X1", "Y1", "X2", "Y2", "Description")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        
        # Define column headings
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=100)
        
        # Add scrollbars
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        # Pack the tree and scrollbars
        tree.grid(column=0, row=0, sticky="nsew")
        vsb.grid(column=1, row=0, sticky="ns")
        hsb.grid(column=0, row=1, sticky="ew")
        
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        
        # Add data to the tree
        for i, box in enumerate(self.bboxes[image_key]):
            box_id = f"Box {i+1}"
            x1 = f"{box['x1']:.4f}"
            y1 = f"{box['y1']:.4f}"
            x2 = f"{box['x2']:.4f}"
            y2 = f"{box['y2']:.4f}"
            description = box.get('description', '')
            
            tree.insert("", "end", values=(box_id, x1, y1, x2, y2, description))
        
        # Add button to highlight a box when selected
        def highlight_selected_box():
            selected_items = tree.selection()
            if not selected_items:
                return
                
            selected_item = selected_items[0]
            box_idx = int(tree.item(selected_item)["values"][0].split()[-1]) - 1
            
            # Get the canvas to highlight on
            canvas = self.canvas
            img_width = self.img_width
            img_height = self.img_height
            
            # Clear previous highlights
            canvas.delete("highlight")
            
            # Get box coordinates
            box = self.bboxes[image_key][box_idx]
            x1 = box['x1'] * img_width
            y1 = box['y1'] * img_height
            x2 = box['x2'] * img_width
            y2 = box['y2'] * img_height
            
            # Create highlighted rectangle
            canvas.create_rectangle(
                x1, y1, x2, y2, 
                outline="yellow", 
                width=3, 
                tags="highlight"
            )
            
            # Ensure the highlighted box is visible
            canvas.update()
        
        # Add button to highlight the selected box
        highlight_btn = ttk.Button(
            preview_window, 
            text="Highlight Selected Box", 
            command=highlight_selected_box
        )
        highlight_btn.pack(pady=10)
        
        # Add button to close the preview
        close_btn = ttk.Button(
            preview_window, 
            text="Close", 
            command=preview_window.destroy
        )
        close_btn.pack(pady=10)
    
    def setup_ui(self):
        """Set up the user interface"""
        self.root = tk.Tk()
        self.root.title(f"Bounding Box Annotator - Seed {self.seed}")
        self.root.geometry("1400x800")
        
        # Create frames
        self.control_frame = ttk.Frame(self.root, padding=10)
        self.control_frame.pack(side=tk.TOP, fill=tk.X)
        
        # Mode selection radio buttons
        mode_frame = ttk.LabelFrame(self.control_frame, text="Mode")
        mode_frame.grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        
        self.mode_var = tk.StringVar(value="single")
        ttk.Radiobutton(mode_frame, text="Single Location", variable=self.mode_var, value="single", 
                        command=self.on_mode_change).grid(row=0, column=0, padx=5, pady=2)
        ttk.Radiobutton(mode_frame, text="Paired Locations", variable=self.mode_var, value="paired", 
                        command=self.on_mode_change).grid(row=0, column=1, padx=5, pady=2)
        
        # Controls for single mode
        self.single_controls = ttk.Frame(self.control_frame)
        self.single_controls.grid(row=0, column=1, padx=10, pady=5, sticky=tk.W)
        
        ttk.Label(self.single_controls, text="Panoid:").grid(row=0, column=0, padx=5, pady=5)
        
        self.panoid_var = tk.StringVar()
        self.panoid_combo = ttk.Combobox(self.single_controls, textvariable=self.panoid_var, 
                                         width=30, values=[str(p) for p in self.panoids])
        self.panoid_combo.grid(row=0, column=1, padx=5, pady=5)
        if self.panoids:
            self.panoid_combo.current(0)
        
        ttk.Button(self.single_controls, text="Load Images", 
                  command=self.load_panoid_images).grid(row=0, column=2, padx=5, pady=5)
        
        # Controls for paired mode
        self.paired_controls = ttk.Frame(self.control_frame)
        self.paired_controls.grid(row=0, column=1, padx=10, pady=5, sticky=tk.W)
        self.paired_controls.grid_remove()  # Hide initially
        
        ttk.Label(self.paired_controls, text="Pair:").grid(row=0, column=0, padx=5, pady=5)
        
        self.pair_var = tk.StringVar()
        max_pair = max(0, len(self.panoids) // 2 - 1)
        self.pair_spinner = ttk.Spinbox(self.paired_controls, from_=0, to=max_pair, 
                                       textvariable=self.pair_var, width=5, wrap=True)
        self.pair_spinner.grid(row=0, column=1, padx=5, pady=5)
        self.pair_var.set("0")
        
        ttk.Button(self.paired_controls, text="Previous Pair", 
                  command=self.prev_pair).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(self.paired_controls, text="Next Pair", 
                  command=self.next_pair).grid(row=0, column=3, padx=5, pady=5)
        ttk.Button(self.paired_controls, text="Load Pair", 
                  command=self.load_paired_images).grid(row=0, column=4, padx=5, pady=5)
        
        # Common controls
        ttk.Button(self.control_frame, text="Save Annotations", 
                  command=self.save_annotations).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(self.control_frame, text="Clear Current", 
                  command=self.clear_current_annotations).grid(row=0, column=3, padx=5, pady=5)
        
        # Preview button will be added dynamically when an image is selected
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Select mode and load images")
        ttk.Label(self.control_frame, textvariable=self.status_var, relief=tk.SUNKEN, 
                 anchor=tk.W).grid(row=1, column=0, columnspan=6, sticky=tk.W+tk.E, padx=5, pady=5)
        
        # Image display area
        self.image_frame = ttk.Frame(self.root)
        self.image_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # Left side for main image
        self.left_frame = ttk.LabelFrame(self.image_frame, text="Main Image")
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.canvas = tk.Canvas(self.left_frame, bg="gray")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Right side for thumbnails
        self.right_frame = ttk.Frame(self.image_frame)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Thumbnail area
        self.thumbnail_area = ttk.LabelFrame(self.right_frame, text="Thumbnails")
        self.thumbnail_area.pack(fill=tk.BOTH, expand=True)
        
        # Scrollbar for the thumbnails
        self.scrollbar = ttk.Scrollbar(self.thumbnail_area, orient=tk.VERTICAL)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.thumbnail_canvas = tk.Canvas(self.thumbnail_area, width=200, yscrollcommand=self.scrollbar.set)
        self.thumbnail_canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.thumbnail_canvas.yview)
        
        # Thumbnail frame inside canvas
        self.thumbnail_frame = ttk.Frame(self.thumbnail_canvas)
        self.thumbnail_canvas.create_window((0, 0), window=self.thumbnail_frame, anchor=tk.NW)
        
        self.thumbnail_canvas.bind("<MouseWheel>", self.on_mousewheel) 
        self.thumbnail_canvas.bind("<Button-4>", self.on_mousewheel)  
        self.thumbnail_canvas.bind("<Button-5>", self.on_mousewheel)
        # Canvas event bindings
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        
        # Ensure the thumbnail area updates its scroll region
        self.thumbnail_frame.bind("<Configure>", self.on_thumbnail_frame_configure)
        
        # Main loop
        self.root.mainloop()
    
    def on_mousewheel(self, event):
        """Handle mouse wheel event for scrolling the thumbnail area"""
        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            self.thumbnail_canvas.yview_scroll(-1, "units")
        elif event.num == 5 or (hasattr(event, 'delta') and event.delta < 0):
            self.thumbnail_canvas.yview_scroll(1, "units")
        return "break"

    def on_mode_change(self):
        """Handle mode change between single and paired"""
        new_mode = self.mode_var.get()
        if new_mode == self.mode:
            return
            
        self.mode = new_mode
        
        if self.mode == "single":
            # Switch to single mode
            self.single_controls.grid()
            self.paired_controls.grid_remove()
            self.left_frame.configure(text="Main Image")
            self.status_var.set("Single Location Mode: Select a panoid and click 'Load Images'")
        else:
            # Switch to paired mode
            self.single_controls.grid_remove()
            self.paired_controls.grid()
            self.left_frame.configure(text="Selected Image")
            self.status_var.set("Paired Locations Mode: Select a pair index and click 'Load Pair'")
            
        # Clear current display
        self.canvas.delete("all")
        for widget in self.thumbnail_frame.winfo_children():
            widget.destroy()
    
    def prev_pair(self):
        """Navigate to previous pair"""
        max_pair = max(0, len(self.panoids) // 2 - 1)
        current = int(self.pair_var.get())
        new_pair = max(0, current - 1)
        self.pair_var.set(str(new_pair))
        self.load_paired_images()
    
    def next_pair(self):
        """Navigate to next pair"""
        max_pair = max(0, len(self.panoids) // 2 - 1)
        current = int(self.pair_var.get())
        new_pair = min(max_pair, current + 1)
        self.pair_var.set(str(new_pair))
        self.load_paired_images()
    
    def load_paired_images(self):
        """Load paired locations for thumbnail display, but still annotate one image at a time"""
        try:
            pair_idx = int(self.pair_var.get())
            if pair_idx < 0 or pair_idx >= len(self.panoids) // 2:
                messagebox.showwarning("Warning", f"Invalid pair index. Must be between 0 and {len(self.panoids) // 2 - 1}.")
                return
                
            # First location (from start of list)
            first_panoid = self.panoids[pair_idx]
            # Second location (from end of list)
            second_panoid = self.panoids[-(pair_idx + 1)]
            
            self.status_var.set(f"Loaded pair {pair_idx}: {first_panoid} and {second_panoid}")
            
            # Get images for both panoids
            first_images = self.get_images_for_panoid(first_panoid)
            second_images = self.get_images_for_panoid(second_panoid)
            
            if not first_images or not second_images:
                messagebox.showwarning("Warning", "Could not find images for the selected pair.")
                return
            
            # Clear current display
            self.canvas.delete("all")
            
            # Clear previous thumbnails
            for widget in self.thumbnail_frame.winfo_children():
                widget.destroy()
            
            # Display thumbnails for both locations
            self.display_paired_thumbnails(first_panoid, first_images, second_panoid, second_images)
            
        except ValueError:
            messagebox.showerror("Error", "Invalid pair index. Please enter a number.")
    
    def display_paired_thumbnails(self, first_panoid, first_images, second_panoid, second_images):
        """Display thumbnails for both locations in the paired mode"""
        row = 0
        
        # First location thumbnails
        ttk.Label(self.thumbnail_frame, text=f"Location 1: Panoid {first_panoid}", 
                  font=("Arial", 12, "bold")).grid(row=row, column=0, pady=10)
        row += 1
        
        for view, image_path in first_images.items():
            # Create a frame for this thumbnail
            thumb_frame = ttk.Frame(self.thumbnail_frame)
            thumb_frame.grid(row=row, column=0, pady=5, padx=5, sticky=tk.W)
            
            # Load and resize the image for thumbnail
            img = Image.open(image_path)
            img.thumbnail((180, 180))
            photo = ImageTk.PhotoImage(img)
            
            # Store reference to prevent garbage collection
            thumb_frame.photo = photo
            
            # Create thumbnail with label
            thumb_label = ttk.Label(thumb_frame, image=photo)
            thumb_label.grid(row=0, column=0)
            ttk.Label(thumb_frame, text=view).grid(row=1, column=0)
            
            # Add click handler
            thumb_label.bind("<Button-1>", lambda e, p=first_panoid, v=view, path=image_path: 
                             self.select_image(p, v, path))
            
            # Mark if already annotated
            image_key = self.get_image_key(view=view, panoid=first_panoid)
            if image_key in self.bboxes and self.bboxes[image_key]:
                annotated_label = ttk.Label(thumb_frame, text="✓", foreground="green", font=("Arial", 16))
                annotated_label.grid(row=0, column=1)
            
            row += 1
        
        # Separator between locations
        ttk.Separator(self.thumbnail_frame, orient='horizontal').grid(
            row=row, column=0, sticky='ew', pady=10)
        row += 1
        
        # Second location thumbnails
        ttk.Label(self.thumbnail_frame, text=f"Location 2: Panoid {second_panoid}", 
                  font=("Arial", 12, "bold")).grid(row=row, column=0, pady=10)
        row += 1
        
        for view, image_path in second_images.items():
            # Create a frame for this thumbnail
            thumb_frame = ttk.Frame(self.thumbnail_frame)
            thumb_frame.grid(row=row, column=0, pady=5, padx=5, sticky=tk.W)
            
            # Load and resize the image for thumbnail
            img = Image.open(image_path)
            img.thumbnail((180, 180))
            photo = ImageTk.PhotoImage(img)
            
            # Store reference to prevent garbage collection
            thumb_frame.photo = photo
            
            # Create thumbnail with label
            thumb_label = ttk.Label(thumb_frame, image=photo)
            thumb_label.grid(row=0, column=0)
            ttk.Label(thumb_frame, text=view).grid(row=1, column=0)
            
            # Add click handler
            thumb_label.bind("<Button-1>", lambda e, p=second_panoid, v=view, path=image_path: 
                             self.select_image(p, v, path))
            
            # Mark if already annotated
            image_key = self.get_image_key(view=view, panoid=second_panoid)
            if image_key in self.bboxes and self.bboxes[image_key]:
                annotated_label = ttk.Label(thumb_frame, text="✓", foreground="green", font=("Arial", 16))
                annotated_label.grid(row=0, column=1)
            
            row += 1
        
        # Update the scroll region
        self.thumbnail_canvas.update_idletasks()
        self.thumbnail_canvas.configure(scrollregion=self.thumbnail_canvas.bbox("all"))
        
        for child in self.thumbnail_frame.winfo_children():
            child.bind("<MouseWheel>", self.on_mousewheel)
            child.bind("<Button-4>", self.on_mousewheel)
            child.bind("<Button-5>", self.on_mousewheel)
    
    def on_thumbnail_frame_configure(self, event):
        """Update the scroll region when the thumbnail frame changes size"""
        self.thumbnail_canvas.configure(scrollregion=self.thumbnail_canvas.bbox("all"))
    
    def load_panoid_images(self):
        """Load images for the selected panoid"""
        if not self.panoid_var.get():
            messagebox.showwarning("Warning", "Please select a panoid first.")
            return
        
        try:
            self.current_panoid = self.panoid_var.get()

            # Clear previous thumbnails
            for widget in self.thumbnail_frame.winfo_children():
                widget.destroy()
            
            # Get images for this panoid
            images = self.get_images_for_panoid(self.current_panoid)

            row = 0
            ttk.Label(self.thumbnail_frame, text=f"Views for Panoid {self.current_panoid}", font=("Arial", 12, "bold")).grid(row=row, column=0, pady=10)
            row += 1
            
            for view, image_path in images.items():
                # Create a frame for this thumbnail
                thumb_frame = ttk.Frame(self.thumbnail_frame)
                thumb_frame.grid(row=row, column=0, pady=5, padx=5, sticky=tk.W)
                
                # Load and resize the image for thumbnail
                img = Image.open(image_path)
                img.thumbnail((180, 180))
                photo = ImageTk.PhotoImage(img)
                
                # Store reference to prevent garbage collection
                thumb_frame.photo = photo
                
                # Create thumbnail with label
                thumb_label = ttk.Label(thumb_frame, image=photo)
                thumb_label.grid(row=0, column=0)
                ttk.Label(thumb_frame, text=view).grid(row=1, column=0)
                
                # Add click handler
                thumb_label.bind("<Button-1>", lambda e, p=self.current_panoid, v=view, path=image_path: 
                                 self.select_image(p, v, path))
                
                # Mark if already annotated
                image_key = self.get_image_key(view=view, panoid=self.current_panoid)
                if image_key in self.bboxes and self.bboxes[image_key]:
                    annotated_label = ttk.Label(thumb_frame, text="✓", foreground="green", font=("Arial", 16))
                    annotated_label.grid(row=0, column=1)
                
                row += 1
            
            self.status_var.set(f"Loaded images for panoid {self.current_panoid}. Click on a thumbnail to annotate.")
            
            # Update the scroll region
            self.thumbnail_canvas.update_idletasks()
            self.thumbnail_canvas.configure(scrollregion=self.thumbnail_canvas.bbox("all"))

            for child in self.thumbnail_frame.winfo_children():
                child.bind("<MouseWheel>", self.on_mousewheel)
                child.bind("<Button-4>", self.on_mousewheel)
                child.bind("<Button-5>", self.on_mousewheel)
        
        except Exception as e:
            messagebox.showerror("Error", f"Invalid panoid: {e}")

    def select_image(self, panoid, view, image_path):
        """Handle selection of an image for annotation (works in both modes)"""
        self.current_panoid = panoid
        self.current_view = view
        self.current_image_path = image_path
        
        # Clear canvas
        self.canvas.delete("all")
        
        # Load and display the image
        img = Image.open(image_path)
        self.tk_image = ImageTk.PhotoImage(img)
        self.canvas.config(width=img.width, height=img.height)
        self.image_id = self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        
        # Store image dimensions for normalization
        self.img_width = img.width
        self.img_height = img.height
        
        # Display any existing bounding boxes
        image_key = self.get_image_key(view=view, panoid=panoid)
        if image_key in self.bboxes:
            for box in self.bboxes[image_key]:
                x1 = box['x1'] * self.img_width
                y1 = box['y1'] * self.img_height
                x2 = box['x2'] * self.img_width
                y2 = box['y2'] * self.img_height
                self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=2, tags="bbox")
                
                # Show description if exists
                if 'description' in box and box['description']:
                    self.canvas.create_text(x1, y1-5, text=box['description'], anchor=tk.SW, fill="red")
        
        # Add a preview button to show all boxes information
        if hasattr(self, 'preview_btn'):
            self.preview_btn.destroy()

        self.preview_btn = ttk.Button(
            self.control_frame, 
            text="Preview Boxes", 
            command=lambda: self.preview_boxes(image_key)
        )
        self.preview_btn.grid(row=0, column=4, padx=5, pady=5)

        self.status_var.set(f"Annotating: Panoid {panoid}'s {view} view. Click and drag to create bounding box.")
    
    # Mouse event handlers
    def on_press(self, event):
        """Handle mouse press event"""
        if not self.current_image_path:
            return
        
        # Store start position
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        
        # Create a new rectangle
        self.current_rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=2, tags="temp_bbox"
        )
    
    def on_drag(self, event):
        """Handle mouse drag event"""
        if not self.current_rect:
            return
        
        # Update rectangle size
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        self.canvas.coords(self.current_rect, self.start_x, self.start_y, cur_x, cur_y)
    
    def on_release(self, event):
        """Handle mouse release event"""
        if not self.current_rect:
            return
        
        # Get final coordinates
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)
        
        # Ensure x1 <= x2 and y1 <= y2
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)
        
        # Normalize coordinates (0-1)
        norm_x1 = x1 / self.img_width
        norm_y1 = y1 / self.img_height
        norm_x2 = x2 / self.img_width
        norm_y2 = y2 / self.img_height
        
        # Check if the box is too small
        if abs(x2 - x1) < 10 or abs(y2 - y1) < 10:
            self.canvas.delete(self.current_rect)
            self.current_rect = None
            return
        
        # Ask for a description (optional)
        description = simpledialog.askstring("Object Description", "Enter object description (optional):", parent=self.root)
        
        # Store the bounding box
        image_key = self.get_image_key(view=self.current_view, panoid=self.current_panoid)
        if image_key not in self.bboxes:
            self.bboxes[image_key] = []
        
        self.bboxes[image_key].append({
            "x1": norm_x1,
            "y1": norm_y1,
            "x2": norm_x2,
            "y2": norm_y2,
            "description": description if description else ""  # Empty string as default
        })
        
        # Change color of the permanent box
        self.canvas.delete(self.current_rect)
        self.canvas.create_rectangle(x1, y1, x2, y2, outline="green", width=2, tags="bbox")
        if description:  # Only display description if provided
            self.canvas.create_text(x1, y1-5, text=description, anchor=tk.SW, fill="green")
        
        self.current_rect = None
        
        # Update status
        self.status_var.set(f"Annotated {self.current_panoid}'s {self.current_view} view with a new bounding box.")
        
        # Also update the thumbnail view to show the annotated checkmark
        if self.mode == "single":
            self.load_panoid_images()
        else:
            self.load_paired_images()

def main():
    parser = argparse.ArgumentParser(description="Bounding Box Annotation Tool for Street View Images")
    parser.add_argument("--seed", type=int, required=True, help="Data ID")
    args = parser.parse_args()
    
    # Start the annotator
    BoundingBoxAnnotator(args.seed)

if __name__ == "__main__":
    main()