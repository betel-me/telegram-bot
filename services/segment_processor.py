# services/segment_processor.py

def split_into_segments(subtitles, segment_length=120):
    """Group subtitle lines into 2-minute (120s) chunks"""
    segments = []
    current = {'start': 0, 'end': segment_length, 'lines': []}
    
    for sub in subtitles:
        if sub['start'] >= current['end']:
            if current['lines']:
                segments.append(current)
            new_start = (sub['start'] // segment_length) * segment_length
            current = {
                'start': new_start,
                'end': new_start + segment_length,
                'lines': []
            }
        current['lines'].append(sub['text'])
    
    if current['lines']:
        segments.append(current)
    
    return segments