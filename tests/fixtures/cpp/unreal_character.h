// Unreal Engine style character header for testing UE macros

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "UnrealCharacter.generated.h"

UENUM(BlueprintType)
enum class ECharacterState : uint8
{
    Idle,
    Walking,
    Running,
    Jumping
};

USTRUCT(BlueprintType)
struct FCharacterStats
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite)
    float Health;

    UPROPERTY(EditAnywhere, BlueprintReadWrite)
    float MaxHealth;

    UPROPERTY(EditAnywhere, BlueprintReadWrite)
    float MovementSpeed;
};

/**
 * A character class demonstrating Unreal Engine patterns.
 */
UCLASS(Blueprintable, BlueprintType)
class MYGAME_API AUnrealCharacter : public ACharacter
{
    GENERATED_BODY()

public:
    AUnrealCharacter();

    virtual void BeginPlay() override;
    virtual void Tick(float DeltaTime) override;

    UFUNCTION(BlueprintCallable, Category = "Character")
    void TakeDamage(float DamageAmount);

    UFUNCTION(BlueprintCallable, Category = "Character")
    void Heal(float HealAmount);

    UFUNCTION(BlueprintPure, Category = "Character")
    float GetHealthPercentage() const;

    UFUNCTION(BlueprintCallable, Category = "Movement")
    void SetMovementState(ECharacterState NewState);

protected:
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stats")
    FCharacterStats Stats;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "State")
    ECharacterState CurrentState;

private:
    void UpdateMovementSpeed();
};
