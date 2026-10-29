import asyncio
from firebase_admin import messaging
from typing import List, Dict, Any


async def send_push_notification(token, title, body):

    if not token:
        return None

    # 메시지 생성
    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        token=token,
    )

    try:
        # 비동기로 메시지 전송
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, messaging.send, message)
        print("Successfully sent message:", response)
        return response
    except Exception as e:
        print("Error sending message:", e)
        return None


async def send_multicast_push_notification(tokens, title, body, batch_size: int = 500):
    """
    여러 사용자에게 동일한 메시지를 전송 (500명 이상도 가능)

    Args:
        tokens: FCM 토큰 리스트
        title: 알림 제목
        body: 알림 내용
        batch_size: 한 번에 전송할 토큰 수 (기본값: 500)
    """
    total_success = 0
    total_failure = 0
    all_failed_tokens = []

    try:
        # 토큰을 batch_size 크기로 나누어 처리
        for i in range(0, len(tokens), batch_size):
            batch_tokens = tokens[i : i + batch_size]

            # 멀티캐스트 메시지 생성
            message = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                tokens=batch_tokens,
            )

            # 비동기로 멀티캐스트 메시지 전송
            loop = asyncio.get_event_loop()
            batch_response = await loop.run_in_executor(
                None, messaging.send_multicast, message
            )

            total_success += batch_response.success_count
            total_failure += batch_response.failure_count

            # 실패한 토큰 확인
            if batch_response.failure_count > 0:
                for idx, resp in enumerate(batch_response.responses):
                    if not resp.success:
                        all_failed_tokens.append(
                            {"token": batch_tokens[idx], "error": resp.exception.code}
                        )

            print(
                f"배치 {i//batch_size + 1} 처리 완료: "
                f"성공 {batch_response.success_count}/{len(batch_tokens)}"
            )

        # 최종 결과 출력
        print(f"\n전체 결과:")
        print(f"총 토큰: {len(tokens)}")
        print(f"성공: {total_success}")
        print(f"실패: {total_failure}")

        if all_failed_tokens:
            print(f"실패한 토큰들: {all_failed_tokens}")

        return {
            "total_tokens": len(tokens),
            "total_success": total_success,
            "total_failure": total_failure,
            "failed_tokens": all_failed_tokens,
        }

    except Exception as e:
        print("멀티캐스트 메시지 전송 중 오류 발생:", e)
        return None


async def send_multiple_different_notifications(
    messages_data: List[Dict[str, Any]], batch_size: int = 500
):
    """
    여러 사용자에게 각각 다른 메시지를 전송 (500명 이상도 가능)

    Args:
        messages_data: 메시지 데이터 리스트
        batch_size: 한 번에 전송할 메시지 수 (기본값: 500)

    messages_data 형식:
    [
        {"token": "token1", "title": "제목1", "body": "내용1"},
        {"token": "token2", "title": "제목2", "body": "내용2"},
        ...
    ]
    """
    # 메시지 객체 생성
    messages = [
        messaging.Message(
            notification=messaging.Notification(
                title=msg_data["title"], body=msg_data["body"]
            ),
            token=msg_data["token"],
        )
        for msg_data in messages_data
    ]

    # 결과를 저장할 변수들
    total_success = 0
    total_failure = 0
    all_failures = []

    try:
        # 메시지를 batch_size 크기로 나누어 처리
        for i in range(0, len(messages), batch_size):
            batch_messages = messages[i : i + batch_size]
            batch_data = messages_data[i : i + batch_size]

            # 비동기로 배치 전송
            loop = asyncio.get_event_loop()
            batch_response = await loop.run_in_executor(
                None, messaging.send_all, batch_messages
            )

            total_success += batch_response.success_count
            total_failure += batch_response.failure_count

            # 실패한 메시지 확인
            if batch_response.failure_count > 0:
                for idx, resp in enumerate(batch_response.responses):
                    if not resp.success:
                        all_failures.append(
                            {
                                "index": i + idx,  # 전체 메시지 중 실제 인덱스
                                "error": resp.exception.code,
                                "message_data": batch_data[idx],
                            }
                        )

            print(
                f"배치 {i//batch_size + 1} 처리 완료: "
                f"성공 {batch_response.success_count}/{len(batch_messages)}"
            )

        # 최종 결과 출력
        print(f"\n전체 결과:")
        print(f"총 메시지: {len(messages)}")
        print(f"성공: {total_success}")
        print(f"실패: {total_failure}")

        if all_failures:
            print(f"실패한 메시지들: {all_failures}")

        return {
            "total_messages": len(messages),
            "total_success": total_success,
            "total_failure": total_failure,
            "failures": all_failures,
        }

    except Exception as e:
        print("메시지 전송 중 오류 발생:", e)
        return None
