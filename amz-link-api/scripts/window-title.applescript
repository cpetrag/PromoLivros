tell application "System Events"
  if not (exists process "Google Chrome for Testing") then
    return "NO_WINDOW"
  end if
  tell process "Google Chrome for Testing"
    set names to name of windows
    return names as text
  end tell
end tell
