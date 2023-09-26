def arrange_chats(chats, user_id):
        '''arranges all unarranged chats of a particular user into bundles of 
        messages
        `chats` is a list of objects of type chat
        user_id is the unique_id of the chat sender
        '''
        arranged_messages = []
        
        if type(chats) == list:
            for chat in chats:
                #A flag that determines whether a message has been added to the arranged_message
                added = False
                if type(chat) == tuple:
                    ''' The message bundle is a packet of a particular user(buyer/seller) the 
                            user with the user_id in the function arg has messaged or chatted with.
                            The bundle contains details about that particular user, and an array of 
                            the messages between the user and the user with the user_id in the function arg'''
                    for arranged_message in arranged_messages:
                        if arranged_message['user_id'] == chat[5] or arranged_message['user_id'] == chat[6]:
                            arranged_message['messages'].append(
                                {
                                    "sent_to":chat[5],
                                    "sent_from":chat[6],
                                    "status":"",
                                    "send_date_and_time":chat[4],
                                    "message":chat[3]
                                }
                            )
                            added = True
                            break
                    if not added:
                        #TODO: We need to get the other data like `username`,`user_profile_image` and `user_type`
                        #from the other classes/models. For now, empty strings would be assigned to them.
                        
                        new_message_bundle = {
                            'user_id':'',
                            'user_name':'',
                            'user_profile_image':'',
                            'user_type':'',
                            'messages':[]
                        }
                        
                        #setting the user_id of the dictionary chat bundle
                        if user_id == chat[5]:
                            new_message_bundle['user_id'] = chat[6]
                        elif user_id == chat[6]:
                            new_message_bundle['user_id'] = chat[5]
                            
                        new_message_bundle['messages'].append(
                            {
                                "sent_to":chat[5],
                                "sent_from":chat[6],
                                "status":"",
                                "send_date_and_time":chat[4],
                                "message":chat[3]
                            }
                        )
                        arranged_messages.append(new_message_bundle)
                        added = True
                            
        return arranged_messages