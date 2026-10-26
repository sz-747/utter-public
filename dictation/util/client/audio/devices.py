"""Microphone selection; runnable in a fresh process to discover hot-plugged devices.

Automatic order: headphones/headsets (AirPods, earbuds, Bluetooth hands-free),
then USB microphones, then the Windows default, then anything else. A
preferred microphone (Config.audio_input_device, set in Utter) goes first
when it is connected; when it is not, the automatic order applies.
"""
import json
import sounddevice as sd

_HEADPHONE_WORDS = ('airpods', 'headset', 'headphone', 'earphone', 'earbud', 'buds', 'hands-free', 'handsfree')
_SKIP_WORDS = ('stereo mix', 'loopback', 'line in')
# Windows aliases for "the default input": still usable as a fallback, but not a mic to pick.
_ALIAS_WORDS = ('sound mapper', 'primary sound capture')
_API_ORDER = {'MME': 0, 'Windows WASAPI': 1, 'Windows DirectSound': 2}


def matches_preferred(name, preferred):
    """MME truncates long device names, so a prefix of either name counts as the same device."""
    if not preferred:
        return False
    a, b = name.lower().strip(), preferred.lower().strip()
    return a.startswith(b) or b.startswith(a)


def rank(name, is_default, preferred=None):
    """Lower is better."""
    lowered = name.lower()
    if matches_preferred(name, preferred):
        return 0
    if any(word in lowered for word in _HEADPHONE_WORDS):
        return 1
    if 'usb' in lowered:
        return 2
    return 3 if is_default else 4


def compatible_inputs(preferred=None, sample_rate=48000):
    apis = sd.query_hostapis()
    default_input = sd.default.device[0]
    choices = []
    for index, info in enumerate(sd.query_devices()):
        name = info['name']
        api = apis[info['hostapi']]['name']
        # WDM-KS lists disconnected hardware on Windows as usable devices.
        if not info['max_input_channels'] or api == 'Windows WDM-KS':
            continue
        if any(word in name.lower() for word in _SKIP_WORDS):
            continue
        try:
            sd.check_input_settings(device=index, samplerate=sample_rate,
                                    channels=min(2, info['max_input_channels']), dtype='float32')
        except sd.PortAudioError:
            continue
        priority = rank(name, index == default_input, preferred)
        choices.append((priority, _API_ORDER.get(api, 3), index, info, api))
    choices.sort(key=lambda item: item[:3])
    return choices


def device_key(choice):
    return [choice[3]['name'], choice[4]]


def available_names(choices):
    """One display name per physical microphone (the same mic appears once per Windows audio API)."""
    names = []
    for choice in choices:
        name = choice[3]['name'].strip()
        if any(word in name.lower() for word in _ALIAS_WORDS):
            continue
        same = next((n for n in names if matches_preferred(n, name)), None)
        if same is None:
            names.append(name)
        elif len(name) > len(same):          # keep the untruncated spelling
            names[names.index(same)] = name
    return names


if __name__ == '__main__':
    import sys
    found = compatible_inputs(sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None)
    print(json.dumps({'chosen': device_key(found[0]) if found else None,
                      'available': available_names(found)}))
