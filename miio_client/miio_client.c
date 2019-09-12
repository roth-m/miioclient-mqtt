/*
 * miio_client_os
 * An open source implementation of the miio_client, which is used by
 * the xiaomi vaccum robots
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

/* Modified by RothM
 * (c)2019 RothM - MIIO Client Server
 * Licensed under GPL v3
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
 */

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>


#include "lib/cJSON/cJSON.h"

#define COUNT_OF(x)                                                            \
  ((sizeof(x) / sizeof(0 [x])) / ((size_t)(!(sizeof(x) % sizeof(0 [x])))))

int main(void);
void accept_local_server(void);
void exit_programm(void);
void print_bin_array(unsigned char *var, size_t length);
void process_global_message(void);
void process_local_client(size_t client_socket_idx);
int read_internal_info(cJSON *payload_json);
int read_local(int client, cJSON *payload_json);
int read_token(cJSON *payload_json);
int read_device_id(cJSON *payload_json);
int request_device_id(void);
int request_token(void);
void setup_server_sockets(void);
void signalhandler(int signum);

// save the last ids and addresses in a map
struct socketaddr_map_item {
  int id;
  struct sockaddr_in address;
};
struct socketaddr_map_item socketaddr_map[10];
size_t socketaddr_map_newest_item = 0;

// todo use real token an device id
static unsigned char robot_token[16] = {0x7f, 0x7f, 0x7f, 0x7f, 0x7f, 0x7f,
                                        0x7f, 0x7f, 0x7f, 0x7f, 0x7f, 0x7f,
                                        0x7f, 0x7f, 0x7f, 0x7f};
static bool robot_token_valid = true; // todo
static uint32_t robot_device_id = 0xafafafaf;
static bool robot_device_id_valid = false;

// sockets
static int local_server_socket;
static int global_server_socket;
static int local_client_sockets[10];
static size_t local_client_sockets_in_use = 0;
static int local_client_socket_internal = -1;

// local pipe file handler
static int pipefd[2];

unsigned char buffer[1024];

int main(void) {
  // signal handler for sigint
  signal(SIGINT, signalhandler);
  signal(SIGTERM, signalhandler);

  // "self-pipe trick"
  // create pipe to be used to interrupt select call incase of a signal
  if (pipe(pipefd) == -1) {
    printf("Failed to create pipe.");
  }

  // create server sockets, bind and listen
  setup_server_sockets();

  for (size_t i = 0; i < COUNT_OF(local_client_sockets); i++) {
    local_client_sockets[i] = -1;
  }

  // handle acitivity
  while (1) {
    if (!robot_device_id_valid && local_client_socket_internal > -1) {
      printf("Requesting device id.\n");
      request_device_id();
    } else if (!robot_token_valid && local_client_socket_internal > -1) {
      printf("Requesting token.\n");
      // request_token();
    }

    // file discriptor set for the sockets and the pipe
    fd_set readfds;

    // highest-numbered file descriptor
    int maxfd = local_server_socket;
    if (global_server_socket > maxfd) {
      maxfd = local_server_socket;
    }
    if (local_client_socket_internal > maxfd) {
      maxfd = local_client_socket_internal;
    }
    if (pipefd[0] > maxfd) {
      maxfd = pipefd[0];
    }

    // reset the file discriptor set and add file discriptors
    FD_ZERO(&readfds);
    FD_SET(pipefd[0], &readfds);
    FD_SET(local_server_socket, &readfds);
    FD_SET(global_server_socket, &readfds);
    FD_SET(local_client_socket_internal, &readfds);
    for (size_t i = 0; i < COUNT_OF(local_client_sockets); i++) {
      int client_socket = local_client_sockets[i];
      if (client_socket >= 0) {
        FD_SET(client_socket, &readfds);
      }
      // update heighest file discriptor
      if (client_socket > maxfd) {
        maxfd = client_socket;
      }
    }

    // wait for activity
    select(maxfd + 1, &readfds, NULL, NULL, NULL);
    if (FD_ISSET(pipefd[0], &readfds)) {
      // self pipe handler was called (signal received)
      break;
    }
    if (FD_ISSET(local_server_socket, &readfds)) {
      accept_local_server();
    }
    if (FD_ISSET(global_server_socket, &readfds)) {
      process_global_message();
    }
    if (FD_ISSET(local_client_socket_internal, &readfds)) {
      ssize_t ret =
          read(local_client_socket_internal, buffer, sizeof(buffer) - 1);
      if (ret < 0) {
        perror("Couldn't read client socket");
        close(local_client_socket_internal);
        local_client_socket_internal = -1;
      } else if (ret == 0) {
        // client disconnected
        printf("local client internal disconnected.\n");
        close(local_client_socket_internal);
        local_client_socket_internal = -1;
      } else {
        // ignore
        if (buffer[ret - 1] != '\0') {
          buffer[ret] = '\0';
        }
        printf("Ingoring message from internal:\n");
        printf("%s\n", buffer);
      }
    }
    for (size_t i = 0; i < COUNT_OF(local_client_sockets); i++) {
      if (FD_ISSET(local_client_sockets[i], &readfds)) {
        // activity on client socket
        process_local_client(i);
      }
    }
  }

  exit_programm();
}

void accept_local_server(void) {
  struct sockaddr_in new_socket_addr;
  socklen_t sockaddr_in_size = sizeof(struct sockaddr_in);
  int new_socket =
      accept(local_server_socket, (struct sockaddr *)&new_socket_addr,
             &sockaddr_in_size);
  if (new_socket == -1) {
    perror("Couldn't accept socket");
    return;
  }

  // add new socket to client sockets if free space
  if (local_client_sockets_in_use < COUNT_OF(local_client_sockets)) {
    for (size_t i = 0; i < COUNT_OF(local_client_sockets); i++) {
      if (local_client_sockets[i] == -1) {
        local_client_sockets[i] = new_socket;
        local_client_sockets_in_use++;
        printf("Local client connected\n");
        break;
      }
    }
  } else {
    // can't handle new socket
    if (close(new_socket) == -1) {
      perror("Couldn't close socket");
    }
  }
}


void exit_programm(void) {
  printf("Closing all sockets.\n");

  close(local_server_socket);
  close(global_server_socket);
  for (size_t i = 0; i < COUNT_OF(local_client_sockets); i++) {
    int client_socket = local_client_sockets[i];
    if (client_socket > -1) {
      close(client_socket);
    }
  }

  exit(EXIT_SUCCESS);
}

int request_device_id(void) {
  char command[] =
      "{\"method\":\"_internal.request_dinfo\",\"params\":\"/mnt/data/miio/\"}";
  printf("sending: %s\n", command);
  if (send(local_client_socket_internal, command, sizeof(command), 0) == -1) {
    perror("Couldn't request internal info");
    close(local_client_socket_internal);
    local_client_socket_internal = -1;
    return -1;
  }
  return 0;
}

int request_token(void) {
  // not sure how this is supposed to work
  char command[] = "{\"method\":\"_internal.request_dtoken\",\"params\":{"
                   "\"dir\":\"/mnt/data/miio/"
                   "\",\"ntoken\":\"0000000000000000\"}";
  printf("sending: %s\n", command);
  if (send(local_client_socket_internal, command, sizeof(command), 0) == -1) {
    perror("Couldn't request token");
    close(local_client_socket_internal);
    local_client_socket_internal = -1;
    return -1;
  }
  return 0;
}

int read_internal_info(cJSON *payload_json) {
  if (read_device_id(payload_json) == 0) {
    return 0;
  } else if (read_token(payload_json) == 0) {
    return 0;
  }
  return -1;
}

int read_local(int client_socket, cJSON *payload_json) {
  cJSON *method = cJSON_GetObjectItemCaseSensitive(payload_json, "method");
  if (cJSON_IsString(method) && (method->valuestring != NULL)) {
    if (strncmp(method->valuestring, "local.query_status", 18) == 0) {
	  char reply[] = "{\"id\":12345,\"method\":\"local.status\",\"params\":\"cloud_connected\"}";
	  printf("sending reply: %s\n", reply);
	  if (send(client_socket, reply, sizeof(reply), 0) == -1) {
	    perror("Couldn't send reply");
	//    close(local_client_socket_internal);
	//    local_client_socket_internal = -1;
	    return -1;
	  }
	  return 0;
    }

   if (strncmp(method->valuestring, "local.query_time", 16) == 0) {
	  char reply[1024];
	  sprintf(reply, "{\"id\":12345,\"method\":\"local.time\",\"params\":%llu}",(unsigned long long)time(NULL));
	  printf("sending reply: %s\n", reply);
	  if (send(client_socket, reply, strlen(reply), 0) == -1) {
	    perror("Couldn't send reply");
	//    close(local_client_socket_internal);
	//    local_client_socket_internal = -1;
	    return -1;
	  }
	  return 0;
    }



  }
  fprintf(stderr, "Received unknown local method!\n.");

  return -1;
}



int read_device_id(cJSON *payload_json) {
  // read json
  cJSON *method = cJSON_GetObjectItemCaseSensitive(payload_json, "method");
  if (cJSON_IsString(method) && (method->valuestring != NULL)) {
    char value[] = "_internal.response_dinfo";
    if (strncmp(method->valuestring, value, strlen(value)) != 0) {
      fprintf(stderr, "Received method is not _internal.response_dinfo\n.");
      return -1;
    }
  }
  cJSON *params = cJSON_GetObjectItemCaseSensitive(payload_json, "params");
  if (!cJSON_IsObject(params)) {
    fprintf(stderr, "No params\n.");
    return -1;
  }
  cJSON *did = cJSON_GetObjectItemCaseSensitive(params, "did");
  if (!cJSON_IsNumber(did)) {
    fprintf(stderr, "Device id wasn't a number.\n");
// RothM    return -1;
  }
  printf("Device id received\n");
// RothM  robot_device_id = did->valueint;
  robot_device_id = 94915579;
  robot_device_id_valid = true;
  return 0;
}

int read_token(cJSON *payload_json) {
  // read json
  cJSON *method = cJSON_GetObjectItemCaseSensitive(payload_json, "method");
  if (cJSON_IsString(method) && (method->valuestring != NULL)) {
    char value[] = "_internal.response_dtoken";
    if (strncmp(method->valuestring, value, strlen(value)) != 0) {
      fprintf(stderr, "Received method is not _internal.response_dtoken.\n");
      return -1;
    }
  }
  cJSON *params = cJSON_GetObjectItemCaseSensitive(payload_json, "params");
  if (cJSON_IsString(method) && (method->valuestring != NULL)) {
    fprintf(stderr, "No device token received\n.");
    return -1;
  }
  if (strlen(params->valuestring) != 16) {
    fprintf(stderr, "Received wrong token size\n.");
    return -1;
  }
  printf("Token received\n");
  memcpy(robot_token, params->valuestring, COUNT_OF(robot_token));
  robot_token_valid = true;
  return 0;
}



void print_bin_array(unsigned char *var, size_t length) {
  for (size_t i = 0; i < length; i++) {
    printf("%02x", var[i]);
  }
  printf("\n");
}


void process_global_message(void) {
  struct sockaddr_in addr;

  socklen_t sockaddr_in_size = sizeof(struct sockaddr_in);
  ssize_t length = recvfrom(global_server_socket, buffer, sizeof(buffer), 0,
                            (struct sockaddr *)&addr, &sockaddr_in_size);
  if (length < 0) {
    perror("Couldn't receive from socket");
    return;
  }
    // add address to map
    if (socketaddr_map_newest_item == 0) {
      socketaddr_map_newest_item = COUNT_OF(socketaddr_map) - 1;
    } else {
      socketaddr_map_newest_item--;
    }
    // RothM socketaddr_map[socketaddr_map_newest_item].id = payload_id;
    socketaddr_map[socketaddr_map_newest_item].id = 0;
    socketaddr_map[socketaddr_map_newest_item].address = addr;

    if(length>3 && strncmp((char *)buffer,"{\"method\": \"internal.PING\"}",27)==0)
    {
	char pong[]="{\"method\": \"internal.PONG\", \"result\": [\"online\"]}";
	sendto(global_server_socket,(char *)&pong,50,0, (struct sockaddr *)&addr, sizeof(struct sockaddr));
	printf("Got PING\n");
    }
    else
    {
	    // send to all local clients
	    for (size_t i = 0; i < COUNT_OF(local_client_sockets); i++) {
	      int client_socket = local_client_sockets[i];
	      if (client_socket > 0) {
// RothM        if (send(client_socket, payload_loc, payload_size, 0) == -1) {
	        if (send(client_socket, buffer, length, 0) == -1) {
	        }
	      }
	    }
    }
// RothM  }
}

void process_local_client(size_t client_socket_idx) {
  char ackmsg[1024];
  int client_socket = local_client_sockets[client_socket_idx];
  unsigned char *payload_loc = &buffer[0x20];
  ssize_t payload_size = sizeof(buffer) - 0x20;
  payload_size = read(client_socket, payload_loc, payload_size - 1);
  if (payload_size < 0) {
    perror("Couldn't read client socket");
    close(client_socket);
    local_client_sockets[client_socket_idx] = -1;
    local_client_sockets_in_use--;
    return;
  } else if (payload_size == 0) {
    // client disconnected
    printf("Local client disconnected.\n");
    close(client_socket);
    local_client_sockets[client_socket_idx] = -1;
    local_client_sockets_in_use--;
    return;
  }

  // ensure zero padding
  if (payload_loc[payload_size] != '\0') {
    payload_loc[payload_size] = '\0';
    payload_size++;
  }

  printf("Received from local client:\n");
  printf("%s\n", payload_loc);

  // read payload
  cJSON *payload_json = cJSON_Parse((char *)payload_loc);
  if (payload_json == NULL) {
    fprintf(stderr, "JSON parse error\n");
    return;
  }
  cJSON *method = cJSON_GetObjectItemCaseSensitive(payload_json, "method");

  if (cJSON_IsString(method) && (method->valuestring != NULL)) {
    char value[] = "_internal.hello";
    if (strncmp(method->valuestring, value, strlen(value)) == 0) {
      printf("got _internal.hello\n");
      // move this socket
      local_client_socket_internal = client_socket;
      local_client_sockets[client_socket_idx] = -1;
      local_client_sockets_in_use--;
      return;
    }
  }
  if (cJSON_IsString(method) && (method->valuestring != NULL)) {
    char internal[] = "_internal.";
    if (strncmp(method->valuestring, internal, strlen(internal)) == 0) {
      printf("Reading _internal message\n");
      if (read_internal_info(payload_json) != 0) {
        fprintf(stderr, "Error reading _internal message!\n");
      }
      return;
    }
  }
  cJSON *id = cJSON_GetObjectItemCaseSensitive(payload_json, "id");
  if (!cJSON_IsNumber(id)) {
    fprintf(stderr, "Invalid payload id.\n");
    return;
  }
  int payload_id = id->valueint;
  if (payload_id < 0) {
    fprintf(stderr, "Payload id is negative.\n");
    return;
  }
  
  if (cJSON_IsString(method) && (method->valuestring != NULL)) {
    char local[] = "local.";
    if (strncmp(method->valuestring, local, strlen(local)) == 0) {
      printf("Reading local message\n");
      if (read_local(client_socket, payload_json) != 0) {
        fprintf(stderr, "Error reading local message!\n");
      }
      return;
    }
  }

  cJSON_Delete(payload_json);

// RothM
  if(payload_id!=12345)
  {
	sprintf(ackmsg,"{\"id\":%d,\"result\":\"ok\"}",payload_id);
	printf("sending reply: %s\n", ackmsg);
	if (send(client_socket, ackmsg, strlen(ackmsg), 0) == -1) {
	    perror("Couldn't send reply");
	}
  }


  // send to newest client with matching id
  size_t socketaddr_map_oldest_item =
      (socketaddr_map_newest_item + 1) % COUNT_OF(socketaddr_map);
  for (size_t i = socketaddr_map_newest_item; i != socketaddr_map_oldest_item;
       i = (i + 1) % COUNT_OF(socketaddr_map)) {
// RothM    if (socketaddr_map[i].id == payload_id) {
// RothM      if (sendto(global_server_socket, buffer, packet_size, 0,
      if (sendto(global_server_socket, payload_loc, payload_size, 0,
                 (struct sockaddr *)&socketaddr_map[i].address,
                 sizeof(struct sockaddr)) == -1) {
        perror("Couldn't forward local client package");
      }
//    }
  }
}

void setup_server_sockets(void) {
  local_server_socket = socket(AF_INET, SOCK_STREAM, 0);
  struct sockaddr_in local_server_addr = {.sin_family = AF_INET,
                                          .sin_addr.s_addr =
                                              htonl(INADDR_LOOPBACK),
                                          .sin_port = htons(54322)};
  global_server_socket = socket(AF_INET, SOCK_DGRAM, 0);
  struct sockaddr_in global_server_addr = {.sin_family = AF_INET,
                                           .sin_addr.s_addr = htonl(INADDR_ANY),
                                           .sin_port = htons(54321)};
  if (setsockopt(local_server_socket, SOL_SOCKET, SO_REUSEADDR, &(int){ 1 }, sizeof(int)) < 0)
    perror("setsockopt(SO_REUSEADDR) failed");

  if (setsockopt(global_server_socket, SOL_SOCKET, SO_REUSEADDR, &(int){ 1 }, sizeof(int)) < 0)
    perror("setsockopt(SO_REUSEADDR) failed");


  if (bind(local_server_socket, (struct sockaddr *)&local_server_addr,
           sizeof(struct sockaddr)) != 0) {
    perror("Couldn't bind local server socket");
    exit_programm();
  }
  if (bind(global_server_socket, (struct sockaddr *)&global_server_addr,
           sizeof(struct sockaddr)) != 0) {
    perror("Couldn't bind global server socket");
    exit_programm();
  }

  if (listen(local_server_socket, 3) != 0) {
    perror("Can't listen to local socket");
    exit_programm();
  }
}

void signalhandler(int signum) {
  (void)signum;
  printf("SIGINT or SIGTERM received.\n");
  write(pipefd[1], "x", 1);
}
