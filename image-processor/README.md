# Image Processor Plugin

An example backend plugin that demonstrates the event system in Calvin.

## Overview

This plugin automatically processes images when they are uploaded to the system. It demonstrates:

1. **Event Subscription**: Subscribes to `image_uploaded` events
2. **Event Handling**: Processes images when events are received
3. **Event Emission**: Emits `image_processed` events when processing is complete
4. **Service Provision**: Provides statistics via the service provider pattern

## Features

- **Automatic Processing**: Processes images as soon as they're uploaded
- **Configurable**: Adjust resize dimensions, thumbnail sizes, etc.
- **Event-Driven**: Uses the event system for non-blocking processing
- **Error Handling**: Emits error events if processing fails

## Configuration

- `enabled`: Enable/disable image processing (default: true)
- `resize_enabled`: Resize large images (default: true)
- `max_width`: Maximum image width in pixels (default: 1920)
- `max_height`: Maximum image height in pixels (default: 1080)
- `generate_thumbnails`: Generate thumbnail versions (default: true)
- `thumbnail_size`: Thumbnail size in pixels (default: 300)

## Event Flow

1. **Image Source** (any method):
   - User uploads via UI → LocalImagePlugin
   - IMAP plugin downloads from email → saves to local directory
   - File system addition → LocalImagePlugin detects it
   - Any other source that adds images to the local directory

2. **System Detection**:
   - LocalImagePlugin.scan_images() detects new images
   - System emits `image_uploaded` event (fire-and-forget)

3. **Image Processing**:
   - ImageProcessorPlugin receives the event asynchronously
   - ImageProcessorPlugin processes the image
   - ImageProcessorPlugin emits `image_processed` event (fire-and-forget)

4. **Other Plugins**:
   - Other plugins can subscribe to `image_processed` events if needed

**Key Design**: The system (LocalImagePlugin) automatically detects new images from ANY source and emits events. Plugins that download images (like IMAP) don't need to emit events - the system handles it automatically.

## Example Usage

```python
# In another plugin, you could subscribe to image_processed events:
async def get_subscribed_events(self) -> list[str]:
    return ["image_processed"]

async def handle_event(self, event_type: str, event_data: dict[str, Any]):
    if event_type == "image_processed":
        image_id = event_data["image_id"]
        results = event_data["processing_results"]
        # Do something with the processed image
        logger.info(f"Image {image_id} was processed: {results}")
```

## Service Provider

The plugin also provides a service that other plugins can use:

```python
# In another plugin:
stats = await backend_plugin.provide_service("get_processing_stats")
# Returns: {"processed_count": 10, "error_count": 0, "total_processed": 10}
```

## Notes

This is a **demonstration plugin** showing event system capabilities. In a real implementation, you would:

- Use PIL/Pillow for actual image resizing
- Implement proper image optimization
- Generate actual thumbnail files
- Handle different image formats
- Add progress reporting

## Installation

This plugin is included in the calvin-plugins repository. Install it via the plugin installer in the Calvin settings UI.
