def get_wellbeing_activity(activity_type: str = 'breathing', stress_score: int = 5, context: str = 'day', events=None):
    activity_type = (activity_type or 'breathing').strip().lower()
    events = events or []
    has_back_to_back = len(events) >= 2
    if activity_type == 'breathing':
        if context == 'bedtime':
            return {'activity_type':'breathing','title':'Night Deep Breathing','duration':'3 minutes','pattern':'deep breathing 4-6','reason':'Best used before bedtime to release mental load and sleep calmer.','steps':['Sit or lie down comfortably','Inhale slowly through the nose for 4 seconds','Exhale gently for 6 seconds','Repeat for 3 minutes']}
        if has_back_to_back and stress_score >= 5:
            return {'activity_type':'breathing','title':'Box Breathing Reset','duration':'90 seconds','pattern':'4-4-4-4','reason':'Back-to-back meetings detected. Box breathing helps restore focus quickly.','steps':['Inhale for 4 seconds','Hold for 4 seconds','Exhale for 4 seconds','Hold for 4 seconds','Repeat for 90 seconds']}
        if stress_score >= 8:
            return {'activity_type':'breathing','title':'Calming Breathing Reset','duration':'2 minutes','pattern':'4-4-6','reason':'High stress score detected. This pattern helps slow the nervous system.','steps':['Inhale for 4 seconds','Hold for 4 seconds','Exhale for 6 seconds','Repeat for 2 minutes']}
        if stress_score >= 6:
            return {'activity_type':'breathing','title':'Midday Focus Breathing','duration':'90 seconds','pattern':'4-4-4','reason':'Moderate stress detected. This helps you regain focus.','steps':['Inhale for 4 seconds','Hold for 4 seconds','Exhale for 4 seconds','Repeat for 90 seconds']}
        return {'activity_type':'breathing','title':'Light Reset','duration':'1 minute','pattern':'slow breathing','reason':'A light breathing pause supports clarity even on easier days.','steps':['Take a slow inhale','Take a slow exhale','Repeat for 1 minute']}
    return {'activity_type':activity_type,'title':'Wellbeing Pause','duration':'1 minute','pattern':'pause','reason':'Short wellbeing fallback activity.','steps':['Take a short pause and reset.']}
