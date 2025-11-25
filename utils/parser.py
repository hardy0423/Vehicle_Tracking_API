import re
class DeviceResponseParser:
    @staticmethod
    def parse_getstatus_response(response):
        """
        Parse the response from the 'getstatus' command.
        Example response: "Data Link: 1 GPRS: 1 Phone: 0 SIM: 0 OP: 64602 Signal: 5 NewSMS: 0 Roaming: 0 SMSFull: 0 LAC: 1651 Cell ID: 4378889 NetType: 2 FwUpd:-65536k"
        """
        parsed_data = {}
        parts = response.split()
        for i in range(0, len(parts), 2):
            if i + 1 < len(parts):
                key = parts[i].rstrip(':')
                value = parts[i + 1]
                parsed_data[key] = value
        return parsed_data

    @staticmethod
    def parse_getinfo_response(response):
        """
        Parse the response from the 'getinfo' command.
        Example response: "RTC:2017/6/16 7:13 Init:2017/6/16 5:44 UpTime:4744s PWR:PwrVoltage RST:0 GPS:2 SAT:0 TTFF:0 TTLF:0 NOGPS: 1:18 SR:0 FG:200 FL:0 SMS: 3 REC:42 MD:1 DB:0"
        """
        cleaned_response = re.sub(r'^.*?(RTC)', r'\1', response)  # Isolates the start of the response to ensure proper parsing
        parsed_data = {}
        parts = cleaned_response.split()
        
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                parsed_data[key.strip()] = value.strip()
            else:
                # Handle cases like "NOGPS: 1:18" where the value contains spaces
                if "NOGPS" in parsed_data:
                    parsed_data["NOGPS"] += " " + part.strip()
        
        # Check and format RTC and Init to include time if missing
        if "RTC" in parsed_data:
            # Ensure RTC includes both date and time (if not already formatted correctly)
            if len(parsed_data["RTC"].split()) == 1:
                parsed_data["RTC"] += " 0:0"  # Defaulting to 0:0 if time is missing
        if "Init" in parsed_data:
            # Ensure Init includes both date and time (if not already formatted correctly)
            if len(parsed_data["Init"].split()) == 1:
                parsed_data["Init"] += " 0:0"  # Defaulting to 0:0 if time is missing

        return parsed_data

    @staticmethod
    def parse_getgps_response(response):
        """
        Parse the response from the 'getgps' command.
        Example response: "GPS:1 Sat:0 Lat:54.666042 Long:25.225031 Alt:0 Speed:0 Dir:0 Date: 2017/6/16 Time: 12:52:30"
        """
        parsed_data = {}
        parts = response.split()
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                parsed_data[key] = value
            else:
                # Handle cases like "Date: 2017/6/16" and "Time: 12:52:30"
                if "Date" in parsed_data:
                    parsed_data["Date"] += " " + part
                elif "Time" in parsed_data:
                    parsed_data["Time"] += " " + part
        return parsed_data
    

    @staticmethod
    def parse_setdigout_response(response):
        """
        Parse the response from the 'setdigout' command.
        """
        cleaned_response = re.sub(r'^.*?(DOUT1)', r'\1', response)
        
        parsed_data = {}
        parts = cleaned_response.split()
        for part in parts:
            if ':' in part:
                key, value = part.split(':', 1)
                parsed_data[key.strip()] = value.strip()
        return parsed_data
    
    @staticmethod
    def parse_setparam_response(response):
        """
        Parse the response from the 'setparam' command.
        This can handle both single and multiple parameters.
        """
        parsed_data = {}

        if "New value" in response:
            params = response.split("New value")[1].strip()
            param_pairs = params.split(';')
            for pair in param_pairs:
                key, value = pair.split(':', 1)
                parsed_data[key] = value

        return parsed_data

    @staticmethod
    def parse_ggps_response(response):
        """
        Parse the response from the 'ggps' command.
        Example response (if no GNSS FIX): "GPS Data not Available. No GPS signal"
        Example response: "D:17/1/9 T:12:52:30 S:0.00 C:54.666042, 25.225032 Url: http://maps.google.com/?q=54.666042,25.225032&om=1speed:0"
        """
        parsed_data = {}
        if "No GPS signal" in response:
            parsed_data["status"] = "No GPS signal"
            response = response.split("No GPS signal")[-1].strip()  # Continue parsing the rest of the response

        cleaned_response = re.sub(r'^.*?(D)', r'\1', response)
        parts = cleaned_response.split()
        for i, part in enumerate(parts):
            if part.startswith("Url:"):
                parsed_data["Url"] = " ".join(parts[i:]).split("Url:")[1]
                break
            elif ':' in part:
                key, value = part.split(':', 1)
                if key == "C":
                    # Combine latitude and longitude into a single value
                    parsed_data[key] = value + " " + parts[i + 1]
                else:
                    parsed_data[key] = value
            elif part.startswith("http"):
                if "Url" in parsed_data:
                    parsed_data["Url"] += " " + part
                else:
                    parsed_data["Url"] = part
        return parsed_data


    @staticmethod
    def parse_response(command, response):
        """
        Parse the response based on the command.
        """
        if command == "getstatus":
            return DeviceResponseParser.parse_getstatus_response(response)
        elif command == "getinfo":
            return DeviceResponseParser.parse_getinfo_response(response)
        elif command == "getgps":
            return DeviceResponseParser.parse_getgps_response(response)
        elif command.startswith("setdigout"):
            return DeviceResponseParser.parse_setdigout_response(response)
        elif command.startswith("setparam"):
            return DeviceResponseParser.parse_setparam_response(response)
        elif command.startswith("ggps"):
            return DeviceResponseParser.parse_ggps_response(response)
        else:
            raise ValueError(f"Unsupported command: {command}")